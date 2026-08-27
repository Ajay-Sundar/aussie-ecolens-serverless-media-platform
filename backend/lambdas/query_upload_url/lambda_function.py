import json
import os
import uuid
import boto3
from datetime import datetime, timezone


# S3 client used to generate temporary upload URLs.
s3_client = boto3.client("s3")

# We reuse the originals bucket, but store query files under query-uploads/.
QUERY_BUCKET = os.environ.get("QUERY_BUCKET", "your-originals-bucket")

# Query uploads are temporary and should not be processed as permanent media.
QUERY_PREFIX = "query-uploads/"

# Supported query file types.
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
        # Parse request body from API Gateway.
        body = json.loads(event.get("body", "{}"))

        # Read query file details.
        filename = body.get("filename")
        content_type = body.get("content_type")

        # Validate filename.
        if not filename:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*"
                },
                "body": json.dumps({
                    "message": "filename is required"
                })
            }

        # Validate content type.
        if not content_type:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*"
                },
                "body": json.dumps({
                    "message": "content_type is required"
                })
            }

        # Reject unsupported query files.
        if content_type not in ALLOWED_CONTENT_TYPES:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*"
                },
                "body": json.dumps({
                    "message": "Unsupported content type",
                    "allowed_content_types": list(ALLOWED_CONTENT_TYPES.keys())
                })
            }

        # Determine whether the query file is an image or video.
        file_type = ALLOWED_CONTENT_TYPES[content_type]

        # Generate temporary query ID.
        query_id = str(uuid.uuid4())

        # Store query files under query-uploads/ so normal S3 processing does not treat them as permanent media.
        query_key = f"{QUERY_PREFIX}{query_id}-{filename}"

        # Generate temporary PUT URL.
        upload_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": QUERY_BUCKET,
                "Key": query_key,
                "ContentType": content_type,
                "Metadata": {
                    "query_id": query_id,
                    "filename": filename,
                    "file_type": file_type,
                    "temporary": "true"
                }
            },
            ExpiresIn=900
        )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "message": "Temporary query upload URL generated",
                "query_id": query_id,
                "query_bucket": QUERY_BUCKET,
                "query_key": query_key,
                "upload_url": upload_url,
                "content_type": content_type,
                "file_type": file_type,
                "temporary": True,
                "created_at": datetime.now(timezone.utc).isoformat()
            })
        }

    except Exception as error:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "message": "Failed to generate temporary query upload URL",
                "error": str(error)
            })
        }

