import json
import os
import os
import hashlib
import boto3
from datetime import datetime, timezone
from urllib.parse import unquote_plus
from PIL import Image
from boto3.dynamodb.conditions import Attr


# Create an S3 client so Lambda can download originals, upload thumbnails, and delete duplicates.
s3_client = boto3.client("s3")

# Create a DynamoDB resource so Lambda can update and scan the media metadata table.
dynamodb = boto3.resource("dynamodb")

# Create a Lambda client so this function can invoke the tagging Lambda.
lambda_client = boto3.client("lambda")

# Store AWS resource names in constants so they are easy to change later.
MEDIA_TABLE_NAME = os.environ.get("MEDIA_TABLE_NAME", "AussieEcoLensMedia")
THUMBNAILS_BUCKET = os.environ.get("THUMBNAILS_BUCKET", "your-thumbnails-bucket")

# Connect to the DynamoDB media metadata table.
media_table = dynamodb.Table(MEDIA_TABLE_NAME)


def calculate_checksum(file_path):
    # Create a SHA-256 hash object.
    sha256_hash = hashlib.sha256()

    # Open the file in binary mode so the checksum is based on exact file bytes.
    with open(file_path, "rb") as file:
        # Read the file in chunks to avoid loading large files fully into memory.
        for chunk in iter(lambda: file.read(8192), b""):
            # Update the checksum with the current file chunk.
            sha256_hash.update(chunk)

    # Return the final checksum as a hexadecimal string.
    return sha256_hash.hexdigest()


def find_existing_file_by_checksum(checksum, current_file_id):
    # Scan DynamoDB for existing records with the same checksum.
    # This is acceptable for assignment scale. In production, a checksum GSI would be better.
    response = media_table.scan(
        FilterExpression=Attr("checksum").eq(checksum)
    )

    # Get matching items from the first scan response.
    items = response.get("Items", [])

    # Continue scanning if DynamoDB returns paginated results.
    while "LastEvaluatedKey" in response:
        response = media_table.scan(
            FilterExpression=Attr("checksum").eq(checksum),
            ExclusiveStartKey=response["LastEvaluatedKey"]
        )

        # Add the next page of matching items.
        items.extend(response.get("Items", []))

    # Return the first matching item that is not the current upload record.
    for item in items:
        # Ignore the current file because we only care about previous uploads.
        if item.get("file_id") != current_file_id:
            return item

    # Return None if no duplicate was found.
    return None


def create_thumbnail(original_path, thumbnail_path, max_size=(300, 300), quality=75):
    # Open the original image from Lambda's temporary storage.
    with Image.open(original_path) as image:
        # Convert the image to RGB so JPEG thumbnails save correctly.
        image = image.convert("RGB")

        # Resize the image while keeping the original aspect ratio.
        image.thumbnail(max_size)

        # Save the thumbnail as a compressed JPEG file.
        image.save(thumbnail_path, "JPEG", quality=quality)


def get_file_type_from_s3(bucket_name, object_key):
    # Ask S3 for the uploaded object's metadata.
    # This tells us whether the object is an image or a video.
    head_response = s3_client.head_object(
        Bucket=bucket_name,
        Key=object_key
    )

    # S3 ContentType should look like image/jpeg, image/png, or video/mp4.
    content_type = head_response.get("ContentType", "application/octet-stream")

    # Custom metadata was added by GenerateUploadUrlFunction during pre-signed URL creation.
    object_metadata = head_response.get("Metadata", {})

    # Prefer the explicit file_type metadata if it exists.
    file_type = object_metadata.get("file_type")

    # Fallback logic in case older uploads do not have custom metadata.
    if not file_type:
        if content_type.startswith("image/"):
            file_type = "image"
        elif content_type.startswith("video/"):
            file_type = "video"
        else:
            file_type = "unknown"

    return content_type, file_type


def lambda_handler(event, context):
    # Print the full event to CloudWatch Logs for debugging.
    print("Received event:")
    print(json.dumps(event))

    # Get the list of S3 event records.
    records = event.get("Records", [])

    # If no records exist, the event is not a valid S3 upload event.
    if not records:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "No S3 records found in event"
            })
        }

    # Process only the first uploaded file for now.
    first_record = records[0]

    # Extract the bucket name from the S3 event.
    bucket_name = first_record["s3"]["bucket"]["name"]

    # Extract and decode the uploaded object's key.
    object_key = unquote_plus(first_record["s3"]["object"]["key"])

    # Safety check: only process files under uploads/.
    # This prevents accidental processing of internal files such as Lambda layer ZIPs.
    if not object_key.startswith("uploads/"):
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Ignored non-upload object",
                "bucket": bucket_name,
                "key": object_key
            })
        }

    # Remove the uploads/ prefix to get the file name with UUID.
    filename_with_uuid = object_key.replace("uploads/", "", 1)

    # Extract the first 36 characters as the UUID file_id.
    file_id = filename_with_uuid[:36]

    # Create a UTC timestamp for processing.
    processed_at = datetime.now(timezone.utc).isoformat()

    # Read the content type and file type from S3 metadata.
    content_type, file_type = get_file_type_from_s3(bucket_name, object_key)

    # Get the original file extension in lowercase.
    file_extension = os.path.splitext(object_key)[1].lower()

    # Build safe temporary file paths inside Lambda's /tmp directory.
    local_original_path = f"/tmp/{file_id}{file_extension}"
    local_thumbnail_path = f"/tmp/{file_id}_thumb.jpg"

    # Build the original S3 URL.
    original_url = f"s3://{bucket_name}/{object_key}"

    # Download the uploaded file from S3 into Lambda temporary storage.
    s3_client.download_file(bucket_name, object_key, local_original_path)

    # Calculate the SHA-256 checksum of the uploaded file.
    checksum = calculate_checksum(local_original_path)

    # Check whether this exact file already exists in the database.
    duplicate_item = find_existing_file_by_checksum(checksum, file_id)

    # If duplicate exists, mark this record as duplicate and remove the newly uploaded object.
    if duplicate_item:
        # Delete the duplicate uploaded object to avoid wasting S3 storage.
        s3_client.delete_object(
            Bucket=bucket_name,
            Key=object_key
        )

        # Update the current DynamoDB record as duplicate.
        media_table.update_item(
            Key={
                "file_id": file_id
            },
            UpdateExpression=(
                "SET #status = :status, "
                "checksum = :checksum, "
                "content_type = :content_type, "
                "file_type = :file_type, "
                "original_url = :original_url, "
                "duplicate_of_file_id = :duplicate_of_file_id, "
                "duplicate_detected_at = :duplicate_detected_at"
            ),
            ExpressionAttributeNames={
                "#status": "status"
            },
            ExpressionAttributeValues={
                ":status": "duplicate",
                ":checksum": checksum,
                ":content_type": content_type,
                ":file_type": file_type,
                ":original_url": original_url,
                ":duplicate_of_file_id": duplicate_item.get("file_id"),
                ":duplicate_detected_at": processed_at
            }
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Duplicate file detected and duplicate S3 object deleted",
                "file_id": file_id,
                "duplicate_of_file_id": duplicate_item.get("file_id"),
                "checksum": checksum,
                "content_type": content_type,
                "file_type": file_type,
                "status": "duplicate"
            })
        }

    # Default thumbnail values.
    # Videos do not need thumbnail fields, so these remain None for videos.
    thumbnail_bucket = None
    thumbnail_key = None
    thumbnail_url = None

    # Decide how to process the file based on its media type.
    if file_type == "image":
        # Images must have thumbnails for UI preview and query results.
        thumbnail_key = f"thumbnails/{file_id}_thumb.jpg"

        # Create a small JPEG thumbnail from the uploaded image.
        create_thumbnail(local_original_path, local_thumbnail_path)

        # Upload the thumbnail to the thumbnails bucket.
        s3_client.upload_file(
            local_thumbnail_path,
            THUMBNAILS_BUCKET,
            thumbnail_key,
            ExtraArgs={
                "ContentType": "image/jpeg"
            }
        )

        # Store thumbnail information for images.
        thumbnail_bucket = THUMBNAILS_BUCKET
        thumbnail_url = f"s3://{THUMBNAILS_BUCKET}/{thumbnail_key}"
        processing_status = "thumbnail_generated"

    elif file_type == "video":
        # Videos skip thumbnail generation.
        # The assignment expects video processing through frame extraction for ML tagging.
        processing_status = "video_uploaded"

    else:
        # Unknown file types should not continue to ML tagging.
        media_table.update_item(
            Key={
                "file_id": file_id
            },
            UpdateExpression=(
                "SET #status = :status, "
                "uploaded_at = :uploaded_at, "
                "checksum = :checksum, "
                "content_type = :content_type, "
                "file_type = :file_type, "
                "original_url = :original_url"
            ),
            ExpressionAttributeNames={
                "#status": "status"
            },
            ExpressionAttributeValues={
                ":status": "unsupported_file_type",
                ":uploaded_at": processed_at,
                ":checksum": checksum,
                ":content_type": content_type,
                ":file_type": file_type,
                ":original_url": original_url
            }
        )

        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "Unsupported file type",
                "file_id": file_id,
                "content_type": content_type,
                "file_type": file_type
            })
        }

    # Update the DynamoDB record with final upload-processing details.
    media_table.update_item(
        Key={
            "file_id": file_id
        },
        UpdateExpression=(
            "SET #status = :status, "
            "uploaded_at = :uploaded_at, "
            "checksum = :checksum, "
            "content_type = :content_type, "
            "file_type = :file_type, "
            "thumbnail_bucket = :thumbnail_bucket, "
            "thumbnail_key = :thumbnail_key, "
            "thumbnail_url = :thumbnail_url, "
            "original_url = :original_url"
        ),
        ExpressionAttributeNames={
            "#status": "status"
        },
        ExpressionAttributeValues={
            ":status": processing_status,
            ":uploaded_at": processed_at,
            ":checksum": checksum,
            ":content_type": content_type,
            ":file_type": file_type,
            ":thumbnail_bucket": thumbnail_bucket,
            ":thumbnail_key": thumbnail_key,
            ":thumbnail_url": thumbnail_url,
            ":original_url": original_url
        }
    )

    # Build the payload for TagUploadedFileFunction.
    # Passing file_type helps the next Lambda and GCP Cloud Run choose image vs video inference.
    tagging_payload = {
        "file_id": file_id,
        "original_bucket": bucket_name,
        "original_key": object_key,
        "content_type": content_type,
        "file_type": file_type
    }

    # Invoke TagUploadedFileFunction asynchronously.
    # This means upload processing does not wait for ML tagging to finish.
    lambda_client.invoke(
        FunctionName="TagUploadedFileFunction",
        InvocationType="Event",
        Payload=json.dumps(tagging_payload).encode("utf-8")
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "File processed, checksum stored, media routing completed, tagging invoked",
            "bucket": bucket_name,
            "key": object_key,
            "file_id": file_id,
            "content_type": content_type,
            "file_type": file_type,
            "checksum": checksum,
            "thumbnail_bucket": thumbnail_bucket,
            "thumbnail_key": thumbnail_key,
            "status": processing_status,
            "tagging_invoked": True
        })
    }


