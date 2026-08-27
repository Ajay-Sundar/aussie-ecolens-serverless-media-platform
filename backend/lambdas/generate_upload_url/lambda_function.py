import json
import os
import uuid
import boto3
from datetime import datetime, timezone


# AWS clients/resources used by this Lambda.
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

# Main S3 bucket where original uploaded media files are stored.
ORIGINALS_BUCKET = os.environ.get("ORIGINALS_BUCKET", "your-originals-bucket")

# DynamoDB table used to store media metadata.
MEDIA_TABLE_NAME = os.environ.get("MEDIA_TABLE_NAME", "AussieEcoLensMedia")
media_table = dynamodb.Table(MEDIA_TABLE_NAME)


# Supported content types for the upload API.
# The dictionary value is the internal file type we store in DynamoDB.
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "image",
    "image/jpg": "image",
    "image/png": "image",
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/x-msvideo": "video"
}


def lambda_handler(event, context):
    try:
        # API Gateway sends the request body as a JSON string.
        body = json.loads(event.get("body", "{}"))

        # Read the filename and content type sent by the client.
        filename = body.get("filename")
        content_type = body.get("content_type")

        # A filename is required because we use it to create the S3 object key.
        if not filename:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "message": "filename is required"
                })
            }

        # A content type is required so the system knows whether this is an image or video.
        if not content_type:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "message": "content_type is required"
                })
            }

        # Reject files that are not part of our supported media types.
        # This keeps the upload pipeline controlled and avoids unexpected files entering S3.
        if content_type not in ALLOWED_CONTENT_TYPES:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "message": "Unsupported content type",
                    "allowed_content_types": list(ALLOWED_CONTENT_TYPES.keys())
                })
            }

        # Convert the content type into our internal file type.
        # Example: image/jpeg -> image, video/mp4 -> video.
        file_type = ALLOWED_CONTENT_TYPES[content_type]

        # Generate a unique ID for this uploaded file.
        file_id = str(uuid.uuid4())

        # Store all uploaded media under the uploads/ prefix.
        file_key = f"uploads/{file_id}-{filename}"

        # Generate a temporary S3 upload URL.
        # The user uploads directly to S3 using this URL.
        upload_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": ORIGINALS_BUCKET,
                "Key": file_key,
                "ContentType": content_type,

                # Store useful metadata on the S3 object itself.
                # This helps downstream Lambda functions understand the uploaded object.
                "Metadata": {
                    "file_id": file_id,
                    "filename": filename,
                    "file_type": file_type
                }
            },
            ExpiresIn=900
        )

        # Create the initial DynamoDB record before the file is uploaded.
        # Later Lambdas will update this same record after processing.
        media_record = {
            "file_id": file_id,
            "original_bucket": ORIGINALS_BUCKET,
            "original_key": file_key,
            "filename": filename,
            "content_type": content_type,
            "file_type": file_type,
            "status": "upload_url_generated",
            "tags": {},
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        media_table.put_item(Item=media_record)

        # Return the upload URL and file metadata to the client.
        return {
            "statusCode": 200,
            "body": json.dumps({
                "file_id": file_id,
                "bucket": ORIGINALS_BUCKET,
                "file_key": file_key,
                "upload_url": upload_url,
                "content_type": content_type,
                "file_type": file_type
            })
        }

    except Exception as error:
        # Return the error clearly so we can debug failed uploads.
        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": "Failed to generate upload URL",
                "error": str(error)
            })
        }


