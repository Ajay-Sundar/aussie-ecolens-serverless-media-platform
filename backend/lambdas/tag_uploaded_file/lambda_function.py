import json
import os
import boto3
import urllib.request
import urllib.error
from datetime import datetime, timezone


# Create a DynamoDB resource so this Lambda can update the media metadata table.
dynamodb = boto3.resource("dynamodb")

# Create an S3 client so this Lambda can generate a pre-signed GET URL for the uploaded media file.
s3_client = boto3.client("s3")

# Create an SNS client so this Lambda can send email notifications through SNS.
sns_client = boto3.client("sns")

# SNS topic used for Aussie EcoLens processing notifications.
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "arn:aws:sns:region:account-id:topic-name")

# Store the DynamoDB table name in one constant so it is easy to change later.
MEDIA_TABLE_NAME = os.environ.get("MEDIA_TABLE_NAME", "AussieEcoLensMedia")

# Connect to the media metadata table.
media_table = dynamodb.Table(MEDIA_TABLE_NAME)

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "replace-me")

# Store the deployed GCP Cloud Run prediction endpoint.
GCP_PREDICT_URL = os.environ.get("GCP_PREDICT_URL", "https://your-cloud-run-service/predict")


def generate_presigned_media_url(bucket_name, object_key):
    # Generate a temporary URL so GCP Cloud Run can download the private S3 media file.
    media_url = s3_client.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": bucket_name,
            "Key": object_key
        },
        ExpiresIn=3600
    )

    # Return the temporary URL to the caller.
    return media_url


def call_gcp_ml_service(file_id, media_url, file_type, content_type):
    # Build the JSON payload for the GCP Cloud Run /predict endpoint.
    # image_url is kept for backward compatibility with the current GCP service.
    # media_url is the cleaner general name for both image and video.
    payload = {
        "file_id": file_id,
        "image_url": media_url,
        "media_url": media_url,
        "file_type": file_type,
        "content_type": content_type
    }

    # Convert the Python dictionary into JSON bytes for the HTTP request body.
    request_body = json.dumps(payload).encode("utf-8")

    # Create the HTTP request to the GCP ML service.
    request = urllib.request.Request(
        GCP_PREDICT_URL,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Api-Key": INTERNAL_API_KEY
        },
        method="POST"
    )

    # Send the request to GCP Cloud Run and wait for the response.
    with urllib.request.urlopen(request, timeout=300) as response:
        # Read the response body returned by GCP.
        response_body = response.read().decode("utf-8")

        # Convert the JSON response back into a Python dictionary.
        return json.loads(response_body)


def publish_tagging_notification(
    file_id,
    original_bucket,
    original_key,
    file_type,
    content_type,
    predicted_tags,
    ml_status,
    model_version,
    tagged_at
):
    # Build the original S3 URL for the notification.
    original_url = f"s3://{original_bucket}/{original_key}"

    # Build a readable notification message.
    message = {
        "message": "Aussie EcoLens media tagging completed",
        "file_id": file_id,
        "file_type": file_type,
        "content_type": content_type,
        "status": ml_status,
        "tags": predicted_tags,
        "model_version": model_version,
        "ml_provider": "gcp_cloud_run_real_ml",
        "original_url": original_url,
        "tagged_at": tagged_at
    }

    # Publish the message to SNS.
    # SNS will forward this to confirmed email subscribers.
    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"Aussie EcoLens tagging completed: {file_type} {file_id}",
        Message=json.dumps(message, indent=2)
    )


def publish_tagging_failure_notification(
    file_id,
    original_bucket,
    original_key,
    file_type,
    content_type,
    error_message
):
    # Build the original S3 URL for the notification if values are available.
    original_url = None

    if original_bucket and original_key:
        original_url = f"s3://{original_bucket}/{original_key}"

    # Build a readable failure notification message.
    message = {
        "message": "Aussie EcoLens media tagging failed",
        "file_id": file_id,
        "file_type": file_type,
        "content_type": content_type,
        "status": "tagging_failed",
        "error": error_message,
        "original_url": original_url,
        "failed_at": datetime.now(timezone.utc).isoformat()
    }

    # Publish the failure message to SNS.
    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"Aussie EcoLens tagging failed: {file_id}",
        Message=json.dumps(message, indent=2)
    )


def lambda_handler(event, context):
    # Print the incoming event so we can debug what ProcessUploadedFileFunction sends.
    print("Received event:")
    print(json.dumps(event))

    # Extract the file_id from the event.
    file_id = event.get("file_id")

    # Extract the original S3 bucket from the event.
    original_bucket = event.get("original_bucket")

    # Extract the original S3 key from the event.
    original_key = event.get("original_key")

    # Extract media metadata passed by ProcessUploadedFileFunction.
    # Defaults keep older image tests working.
    content_type = event.get("content_type", "image/jpeg")
    file_type = event.get("file_type")

    # If file_type was not passed, infer it from content_type.
    if not file_type:
        if content_type.startswith("image/"):
            file_type = "image"
        elif content_type.startswith("video/"):
            file_type = "video"
        else:
            file_type = "unknown"

    # Validate that the required values were provided.
    if not file_id or not original_bucket or not original_key:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "Missing file_id, original_bucket, or original_key"
            })
        }

    # Reject unknown file types before calling GCP.
    if file_type not in ["image", "video"]:
        error_message = f"Unsupported file_type for tagging: {file_type}"

        media_table.update_item(
            Key={
                "file_id": file_id
            },
            UpdateExpression="SET #status = :status, tagging_error = :tagging_error",
            ExpressionAttributeNames={
                "#status": "status"
            },
            ExpressionAttributeValues={
                ":status": "tagging_failed",
                ":tagging_error": error_message
            }
        )

        # Send a failure notification for unsupported file types.
        try:
            publish_tagging_failure_notification(
                file_id=file_id,
                original_bucket=original_bucket,
                original_key=original_key,
                file_type=file_type,
                content_type=content_type,
                error_message=error_message
            )
        except Exception as sns_error:
            # Do not fail the Lambda just because notification failed.
            print("SNS failure notification failed:")
            print(str(sns_error))

        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "Unsupported file_type for tagging",
                "file_id": file_id,
                "file_type": file_type,
                "content_type": content_type
            })
        }

    try:
        # Generate a temporary pre-signed URL for the uploaded media file in S3.
        media_url = generate_presigned_media_url(original_bucket, original_key)

        # Call the deployed GCP Cloud Run ML service.
        ml_result = call_gcp_ml_service(
            file_id=file_id,
            media_url=media_url,
            file_type=file_type,
            content_type=content_type
        )

        # Extract tags from the GCP response.
        predicted_tags = ml_result.get("tags", {})

        # Extract model version from the GCP response.
        model_version = ml_result.get("model_version", "unknown_gcp_model")

        # Prefer status from GCP if available, otherwise use tagged.
        ml_status = ml_result.get("status", "tagged")

        # Store the current UTC time as the tagging timestamp.
        tagged_at = datetime.now(timezone.utc).isoformat()

        # Update DynamoDB with the predicted tags and tagging metadata.
        media_table.update_item(
            Key={
                "file_id": file_id
            },
            UpdateExpression=(
                "SET #status = :status, "
                "tags = :tags, "
                "model_version = :model_version, "
                "tagged_at = :tagged_at, "
                "ml_provider = :ml_provider, "
                "content_type = :content_type, "
                "file_type = :file_type"
            ),
            ExpressionAttributeNames={
                "#status": "status"
            },
            ExpressionAttributeValues={
                ":status": ml_status,
                ":tags": predicted_tags,
                ":model_version": model_version,
                ":tagged_at": tagged_at,
                ":ml_provider": "gcp_cloud_run_real_ml",
                ":content_type": content_type,
                ":file_type": file_type
            }
        )

        # Send SNS notification after DynamoDB has been updated successfully.
        # This is wrapped in its own try block so tagging does not fail if email notification fails.
        sns_notification_sent = False
        sns_notification_error = None

        try:
            publish_tagging_notification(
                file_id=file_id,
                original_bucket=original_bucket,
                original_key=original_key,
                file_type=file_type,
                content_type=content_type,
                predicted_tags=predicted_tags,
                ml_status=ml_status,
                model_version=model_version,
                tagged_at=tagged_at
            )

            sns_notification_sent = True

        except Exception as sns_error:
            sns_notification_error = str(sns_error)
            print("SNS success notification failed:")
            print(sns_notification_error)

        # Return useful output so we can confirm the function worked.
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Real GCP ML tagging completed and DynamoDB updated",
                "file_id": file_id,
                "tags": predicted_tags,
                "status": ml_status,
                "model_version": model_version,
                "ml_provider": "gcp_cloud_run_real_ml",
                "content_type": content_type,
                "file_type": file_type,
                "sns_notification_sent": sns_notification_sent,
                "sns_notification_error": sns_notification_error
            })
        }

    except urllib.error.HTTPError as error:
        # Try to read the error body returned by GCP Cloud Run.
        error_body = error.read().decode("utf-8")

        # Log HTTP errors returned by GCP Cloud Run.
        print("HTTP error from GCP ML service:")
        print(error_body)

        # Mark the DynamoDB item so we can see tagging failed.
        media_table.update_item(
            Key={
                "file_id": file_id
            },
            UpdateExpression=(
                "SET #status = :status, "
                "tagging_error = :tagging_error, "
                "content_type = :content_type, "
                "file_type = :file_type"
            ),
            ExpressionAttributeNames={
                "#status": "status"
            },
            ExpressionAttributeValues={
                ":status": "tagging_failed",
                ":tagging_error": error_body,
                ":content_type": content_type,
                ":file_type": file_type
            }
        )

        # Send failure notification if GCP returns an HTTP error.
        try:
            publish_tagging_failure_notification(
                file_id=file_id,
                original_bucket=original_bucket,
                original_key=original_key,
                file_type=file_type,
                content_type=content_type,
                error_message=error_body
            )
        except Exception as sns_error:
            print("SNS failure notification failed:")
            print(str(sns_error))

        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": "GCP ML service returned an HTTP error",
                "error": error_body,
                "file_id": file_id,
                "content_type": content_type,
                "file_type": file_type
            })
        }

    except Exception as error:
        # Log unexpected errors for debugging.
        print("Unexpected tagging error:")
        print(str(error))

        # Mark the DynamoDB item so we can see tagging failed.
        media_table.update_item(
            Key={
                "file_id": file_id
            },
            UpdateExpression=(
                "SET #status = :status, "
                "tagging_error = :tagging_error, "
                "content_type = :content_type, "
                "file_type = :file_type"
            ),
            ExpressionAttributeNames={
                "#status": "status"
            },
            ExpressionAttributeValues={
                ":status": "tagging_failed",
                ":tagging_error": str(error),
                ":content_type": content_type,
                ":file_type": file_type
            }
        )

        # Send failure notification for unexpected tagging errors.
        try:
            publish_tagging_failure_notification(
                file_id=file_id,
                original_bucket=original_bucket,
                original_key=original_key,
                file_type=file_type,
                content_type=content_type,
                error_message=str(error)
            )
        except Exception as sns_error:
            print("SNS failure notification failed:")
            print(str(sns_error))

        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": "Unexpected error while calling GCP ML service",
                "error": str(error),
                "file_id": file_id,
                "content_type": content_type,
                "file_type": file_type
            })
        }


