import json
import os
import boto3
from decimal import Decimal
import urllib.request
import urllib.error
from datetime import datetime, timezone


# Create a DynamoDB resource so this Lambda can read metadata from the media table.
dynamodb = boto3.resource("dynamodb")

# Create an S3 client so this Lambda can delete originals/thumbnails and create pre-signed GET URLs.
s3_client = boto3.client("s3")

# Store the DynamoDB table name in one constant so it is easy to change later.
MEDIA_TABLE_NAME = os.environ.get("MEDIA_TABLE_NAME", "AussieEcoLensMedia")

# Store the deployed GCP Cloud Run prediction endpoint.
GCP_PREDICT_URL = os.environ.get("GCP_PREDICT_URL", "https://your-cloud-run-service/predict")

# Internal API key used by AWS Lambda to authenticate with the protected GCP Cloud Run /predict endpoint.
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "replace-me")

# Connect to the media metadata table.
media_table = dynamodb.Table(MEDIA_TABLE_NAME)


def decimal_to_json_safe(value):
    # Convert DynamoDB Decimal values into normal int/float values for JSON responses.
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)

    if isinstance(value, list):
        return [decimal_to_json_safe(item) for item in value]

    if isinstance(value, dict):
        return {
            key: decimal_to_json_safe(item_value)
            for key, item_value in value.items()
        }

    return value


def build_response(status_code, body):
    # Build a standard API Gateway response with CORS enabled.
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS"
        },
        "body": json.dumps(decimal_to_json_safe(body))
    }


def get_path_parameters(event):
    # Safely extract path parameters from API Gateway event.
    return event.get("pathParameters") or {}


def get_route(event):
    # API Gateway HTTP API v2 sends routeKey.
    return event.get("routeKey", "")


def parse_json_body(event):
    # API Gateway sends request body as a JSON string.
    body_text = event.get("body") or "{}"

    try:
        return json.loads(body_text)
    except json.JSONDecodeError:
        return None


def scan_all_media_items():
    # Scan all media items from DynamoDB.
    # For assignment scale this is acceptable. In production, indexes would be better.
    response = media_table.scan()
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = media_table.scan(
            ExclusiveStartKey=response["LastEvaluatedKey"]
        )
        items.extend(response.get("Items", []))

    return items


def get_file_by_id(file_id):
    # Retrieve one item from DynamoDB using the partition key.
    response = media_table.get_item(
        Key={
            "file_id": file_id
        }
    )

    item = response.get("Item")

    if not item:
        return build_response(404, {
            "message": "File not found",
            "file_id": file_id
        })

    return build_response(200, {
        "message": "File metadata retrieved",
        "item": item
    })


def get_urls_for_file(file_id):
    # Retrieve one item from DynamoDB using the partition key.
    response = media_table.get_item(
        Key={
            "file_id": file_id
        }
    )

    item = response.get("Item")

    if not item:
        return build_response(404, {
            "message": "File not found",
            "file_id": file_id
        })

    return build_response(200, {
        "message": "File URLs retrieved",
        "file_id": file_id,
        "original_url": item.get("original_url"),
        "thumbnail_url": item.get("thumbnail_url"),
        "original_bucket": item.get("original_bucket"),
        "original_key": item.get("original_key"),
        "thumbnail_bucket": item.get("thumbnail_bucket"),
        "thumbnail_key": item.get("thumbnail_key")
    })


def build_query_result_item(item):
    # Build a response item suitable for query results.
    # Images return thumbnail_url for preview.
    # Videos return original_url directly because videos do not require thumbnails.
    file_type = item.get("file_type", "unknown")

    return {
        "file_id": item.get("file_id"),
        "filename": item.get("filename"),
        "file_type": file_type,
        "content_type": item.get("content_type"),
        "status": item.get("status"),
        "tags": item.get("tags", {}),
        "original_url": item.get("original_url"),
        "thumbnail_url": item.get("thumbnail_url"),
        "result_url": item.get("thumbnail_url") if file_type == "image" else item.get("original_url"),
        "url_type": "thumbnail" if file_type == "image" else "original_video",
        "model_version": item.get("model_version"),
        "ml_provider": item.get("ml_provider"),
        "uploaded_at": item.get("uploaded_at"),
        "tagged_at": item.get("tagged_at")
    }


def query_files_by_tag(tag_name):
    # Scan all media records.
    items = scan_all_media_items()
    matching_items = []

    for item in items:
        # Only return successfully tagged records.
        if item.get("status") != "tagged":
            continue

        tags = item.get("tags", {})

        if tag_name in tags:
            matching_items.append(build_query_result_item(item))

    return build_response(200, {
        "message": "Files retrieved by tag",
        "tag": tag_name,
        "count": len(matching_items),
        "items": matching_items
    })


def query_files_by_tag_counts(event):
    # Parse JSON body from POST request.
    body = parse_json_body(event)

    if body is None:
        return build_response(400, {
            "message": "Invalid JSON body"
        })

    requested_tags = body.get("tags")

    # Validate that tags is a non-empty JSON object.
    if not isinstance(requested_tags, dict) or not requested_tags:
        return build_response(400, {
            "message": "Request body must include a non-empty tags object",
            "example": {
                "tags": {
                    "Canis_familiaris": 1
                }
            }
        })

    # Validate requested counts.
    for tag_name, minimum_count in requested_tags.items():
        if not isinstance(tag_name, str) or not tag_name:
            return build_response(400, {
                "message": "Each tag name must be a non-empty string"
            })

        if not isinstance(minimum_count, int) or minimum_count < 1:
            return build_response(400, {
                "message": "Each tag minimum count must be an integer greater than or equal to 1",
                "invalid_tag": tag_name,
                "invalid_count": minimum_count
            })

    # Scan all media records.
    items = scan_all_media_items()
    matching_items = []

    for item in items:
        # Only return successfully tagged records.
        if item.get("status") != "tagged":
            continue

        item_tags = item.get("tags", {})
        matches_all_tags = True

        # Apply logical AND across all requested tags.
        for requested_tag, minimum_count in requested_tags.items():
            stored_count = item_tags.get(requested_tag, 0)
            stored_count = decimal_to_json_safe(stored_count)

            if int(stored_count) < minimum_count:
                matches_all_tags = False
                break

        if matches_all_tags:
            matching_items.append(build_query_result_item(item))

    return build_response(200, {
        "message": "Files retrieved by tag-count query",
        "query": {
            "tags": requested_tags,
            "logic": "AND",
            "minimum_count_rule": "stored tag count must be greater than or equal to requested count"
        },
        "count": len(matching_items),
        "items": matching_items
    })


def search_by_thumbnail_url(event):
    # Parse JSON body from POST request.
    body = parse_json_body(event)

    if body is None:
        return build_response(400, {
            "message": "Invalid JSON body"
        })

    thumbnail_url = body.get("thumbnail_url")

    if not thumbnail_url or not isinstance(thumbnail_url, str):
        return build_response(400, {
            "message": "Request body must include thumbnail_url",
            "example": {
                "thumbnail_url": "s3://your-thumbnails-bucket/thumbnails/example_thumb.jpg"
            }
        })

    items = scan_all_media_items()

    for item in items:
        if item.get("thumbnail_url") == thumbnail_url:
            return build_response(200, {
                "message": "Original file retrieved from thumbnail URL",
                "thumbnail_url": thumbnail_url,
                "file_id": item.get("file_id"),
                "filename": item.get("filename"),
                "file_type": item.get("file_type"),
                "content_type": item.get("content_type"),
                "original_url": item.get("original_url"),
                "original_bucket": item.get("original_bucket"),
                "original_key": item.get("original_key"),
                "tags": item.get("tags", {})
            })

    return build_response(404, {
        "message": "No file found for the provided thumbnail_url",
        "thumbnail_url": thumbnail_url
    })


def find_item_by_url(target_url):
    # Scan all media records to find a file by original_url or thumbnail_url.
    items = scan_all_media_items()

    for item in items:
        if item.get("original_url") == target_url or item.get("thumbnail_url") == target_url:
            return item

    return None


def parse_s3_url(s3_url):
    # Validate the URL format.
    if not isinstance(s3_url, str) or not s3_url.startswith("s3://"):
        return None, None

    without_prefix = s3_url.replace("s3://", "", 1)
    parts = without_prefix.split("/", 1)

    if len(parts) != 2:
        return None, None

    bucket_name = parts[0]
    object_key = parts[1]

    return bucket_name, object_key


def generate_presigned_get_url(bucket_name, object_key):
    # Generate a temporary URL so GCP Cloud Run can download the query file.
    return s3_client.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": bucket_name,
            "Key": object_key
        },
        ExpiresIn=900
    )


def call_gcp_for_query_file(query_id, media_url, file_type, content_type):
    # Build payload for Cloud Run. Keep image_url for backward compatibility.
    payload = {
        "file_id": query_id,
        "media_url": media_url,
        "image_url": media_url,
        "file_type": file_type,
        "content_type": content_type
    }

    request_body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        GCP_PREDICT_URL,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Api-Key": INTERNAL_API_KEY
        },
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=300) as response:
        response_body = response.read().decode("utf-8")
        return json.loads(response_body)


def find_matching_items_for_tags(detected_tags):
    # If no tags were detected, there is nothing to match.
    if not detected_tags:
        return []

    items = scan_all_media_items()
    matching_items = []

    for item in items:
        # Only search successfully tagged files.
        if item.get("status") != "tagged":
            continue

        item_tags = item.get("tags", {})
        matches_all_tags = True

        # The detected tags from the query file become the search condition.
        # Example: {"Canis_familiaris": 1} means stored item must have Canis_familiaris >= 1.
        for tag_name, detected_count in detected_tags.items():
            stored_count = decimal_to_json_safe(item_tags.get(tag_name, 0))
            detected_count = decimal_to_json_safe(detected_count)

            if int(stored_count) < int(detected_count):
                matches_all_tags = False
                break

        if matches_all_tags:
            matching_items.append(build_query_result_item(item))

    return matching_items


def bulk_update_tags(event):
    # Parse JSON body from POST request.
    body = parse_json_body(event)

    if body is None:
        return build_response(400, {
            "message": "Invalid JSON body"
        })

    urls = body.get("urls")
    requested_tags = body.get("tags")
    operation = body.get("operation")

    if not isinstance(urls, list) or not urls:
        return build_response(400, {
            "message": "Request body must include a non-empty urls list"
        })

    if not isinstance(requested_tags, dict) or not requested_tags:
        return build_response(400, {
            "message": "Request body must include a non-empty tags object"
        })

    if operation not in [0, 1]:
        return build_response(400, {
            "message": "operation must be 1 for add/update or 0 for remove"
        })

    for tag_name, tag_count in requested_tags.items():
        if not isinstance(tag_name, str) or not tag_name:
            return build_response(400, {
                "message": "Each tag name must be a non-empty string"
            })

        if operation == 1:
            if not isinstance(tag_count, int) or tag_count < 1:
                return build_response(400, {
                    "message": "For add operation, each tag count must be an integer greater than or equal to 1",
                    "invalid_tag": tag_name,
                    "invalid_count": tag_count
                })

    results = []

    for target_url in urls:
        if not isinstance(target_url, str) or not target_url:
            results.append({
                "url": target_url,
                "status": "failed",
                "message": "Invalid URL"
            })
            continue

        item = find_item_by_url(target_url)

        if not item:
            results.append({
                "url": target_url,
                "status": "not_found",
                "message": "No media item found for URL"
            })
            continue

        file_id = item.get("file_id")
        current_tags = decimal_to_json_safe(item.get("tags", {}))

        if not isinstance(current_tags, dict):
            current_tags = {}

        if operation == 1:
            # Add or update tags.
            # If a tag exists, increase its count by the requested amount.
            for tag_name, tag_count in requested_tags.items():
                current_count = int(current_tags.get(tag_name, 0))
                current_tags[tag_name] = current_count + int(tag_count)

            action = "tags_added"

        else:
            # Remove tags. Missing tags are ignored.
            for tag_name in requested_tags.keys():
                if tag_name in current_tags:
                    del current_tags[tag_name]

            action = "tags_removed"

        media_table.update_item(
            Key={
                "file_id": file_id
            },
            UpdateExpression="SET tags = :tags, manual_tags_updated_at = :manual_tags_updated_at",
            ExpressionAttributeValues={
                ":tags": current_tags,
                ":manual_tags_updated_at": datetime.now(timezone.utc).isoformat()
            }
        )

        results.append({
            "url": target_url,
            "file_id": file_id,
            "status": "updated",
            "action": action,
            "tags": current_tags
        })

    return build_response(200, {
        "message": "Bulk tag operation completed",
        "operation": operation,
        "operation_meaning": "add/update" if operation == 1 else "remove",
        "requested_tags": requested_tags,
        "results": results
    })


def delete_files(event):
    # Parse JSON body from DELETE request.
    body = parse_json_body(event)

    if body is None:
        return build_response(400, {
            "message": "Invalid JSON body"
        })

    urls = body.get("urls")

    if not isinstance(urls, list) or not urls:
        return build_response(400, {
            "message": "Request body must include a non-empty urls list",
            "example": {
                "urls": [
                    "s3://your-originals-bucket/uploads/example.jpg"
                ]
            }
        })

    results = []

    for target_url in urls:
        if not isinstance(target_url, str) or not target_url:
            results.append({
                "url": target_url,
                "status": "failed",
                "message": "Invalid URL"
            })
            continue

        item = find_item_by_url(target_url)

        if not item:
            results.append({
                "url": target_url,
                "status": "not_found",
                "message": "No media item found for URL"
            })
            continue

        file_id = item.get("file_id")
        original_url = item.get("original_url")
        thumbnail_url = item.get("thumbnail_url")
        deleted_objects = []

        # Delete original file from S3 if available.
        if original_url:
            original_bucket, original_key = parse_s3_url(original_url)

            if original_bucket and original_key:
                try:
                    s3_client.delete_object(
                        Bucket=original_bucket,
                        Key=original_key
                    )

                    deleted_objects.append({
                        "type": "original",
                        "bucket": original_bucket,
                        "key": original_key,
                        "status": "deleted"
                    })

                except Exception as error:
                    deleted_objects.append({
                        "type": "original",
                        "bucket": original_bucket,
                        "key": original_key,
                        "status": "delete_failed",
                        "error": str(error)
                    })

        # Delete thumbnail file from S3 if available.
        if thumbnail_url:
            thumbnail_bucket, thumbnail_key = parse_s3_url(thumbnail_url)

            if thumbnail_bucket and thumbnail_key:
                try:
                    s3_client.delete_object(
                        Bucket=thumbnail_bucket,
                        Key=thumbnail_key
                    )

                    deleted_objects.append({
                        "type": "thumbnail",
                        "bucket": thumbnail_bucket,
                        "key": thumbnail_key,
                        "status": "deleted"
                    })

                except Exception as error:
                    deleted_objects.append({
                        "type": "thumbnail",
                        "bucket": thumbnail_bucket,
                        "key": thumbnail_key,
                        "status": "delete_failed",
                        "error": str(error)
                    })

        # Delete DynamoDB record.
        media_table.delete_item(
            Key={
                "file_id": file_id
            }
        )

        results.append({
            "url": target_url,
            "file_id": file_id,
            "status": "deleted",
            "deleted_objects": deleted_objects,
            "dynamodb_record": "deleted"
        })

    return build_response(200, {
        "message": "Delete files operation completed",
        "results": results
    })


def search_by_query_upload(event):
    # Parse JSON body from POST request.
    body = parse_json_body(event)

    if body is None:
        return build_response(400, {
            "message": "Invalid JSON body"
        })

    query_bucket = body.get("query_bucket")
    query_key = body.get("query_key")
    file_type = body.get("file_type", "image")
    content_type = body.get("content_type", "image/jpeg")

    if not query_bucket or not query_key:
        return build_response(400, {
            "message": "Request body must include query_bucket and query_key",
            "example": {
                "query_bucket": "your-originals-bucket",
                "query_key": "query-uploads/example-query-file.jpg",
                "file_type": "image",
                "content_type": "image/jpeg"
            }
        })

    # Safety check: only allow temporary query uploads.
    if not query_key.startswith("query-uploads/"):
        return build_response(400, {
            "message": "query_key must start with query-uploads/ so permanent media files are not accidentally deleted",
            "query_key": query_key
        })

    if file_type not in ["image", "video"]:
        return build_response(400, {
            "message": "Unsupported file_type",
            "file_type": file_type
        })

    # Query key format is query-uploads/<uuid>-filename.ext.
    filename_with_query_id = query_key.replace("query-uploads/", "", 1)
    query_id = filename_with_query_id[:36]

    try:
        # Generate temporary GET URL for Cloud Run to download the query file.
        media_url = generate_presigned_get_url(query_bucket, query_key)

        # Run ML on the temporary query file.
        ml_result = call_gcp_for_query_file(
            query_id=query_id,
            media_url=media_url,
            file_type=file_type,
            content_type=content_type
        )

        detected_tags = ml_result.get("tags", {})

        # Find existing media records that contain the detected query tags.
        matching_items = find_matching_items_for_tags(detected_tags)

        # Delete the temporary query file so it is not permanently stored.
        s3_client.delete_object(
            Bucket=query_bucket,
            Key=query_key
        )

        return build_response(200, {
            "message": "Files retrieved by uploaded query file",
            "query_file": {
                "query_bucket": query_bucket,
                "query_key": query_key,
                "file_type": file_type,
                "content_type": content_type,
                "temporary_file_deleted": True
            },
            "detected_tags": detected_tags,
            "count": len(matching_items),
            "items": matching_items
        })

    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8")

        try:
            s3_client.delete_object(
                Bucket=query_bucket,
                Key=query_key
            )
        except Exception:
            pass

        return build_response(500, {
            "message": "GCP ML service returned an error while processing query upload",
            "error": error_body,
            "temporary_file_deleted": True
        })

    except Exception as error:
        try:
            s3_client.delete_object(
                Bucket=query_bucket,
                Key=query_key
            )
        except Exception:
            pass

        return build_response(500, {
            "message": "Unexpected error while processing query upload",
            "error": str(error),
            "temporary_file_deleted": True
        })


def get_tag_summary():
    # Scan all media items so we can count tags across the metadata table.
    items = scan_all_media_items()

    tag_counts = {}
    file_counts = {}

    for item in items:
        tags = item.get("tags", {})

        for tag_name, tag_value in tags.items():
            safe_value = decimal_to_json_safe(tag_value)

            tag_counts[tag_name] = tag_counts.get(tag_name, 0) + int(safe_value)
            file_counts[tag_name] = file_counts.get(tag_name, 0) + 1

    return build_response(200, {
        "message": "Tag summary retrieved",
        "total_files_scanned": len(items),
        "tag_counts": tag_counts,
        "file_counts": file_counts
    })


def lambda_handler(event, context):
    # Log the incoming event for debugging API Gateway route issues.
    print("Received event:")
    print(json.dumps(event))

    # Handle browser/API Gateway preflight requests.
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return build_response(200, {
            "message": "CORS preflight successful"
        })

    route_key = get_route(event)
    path_parameters = get_path_parameters(event)

    file_id = path_parameters.get("file_id")
    tag_name = path_parameters.get("tag_name")

    # Route: GET /media/tag-summary
    if route_key == "GET /media/tag-summary":
        return get_tag_summary()

    # Route: POST /media/search-by-tags
    if route_key == "POST /media/search-by-tags":
        return query_files_by_tag_counts(event)

    # Route: POST /media/search-by-thumbnail
    if route_key == "POST /media/search-by-thumbnail":
        return search_by_thumbnail_url(event)

    # Route: POST /media/bulk-tags
    if route_key == "POST /media/bulk-tags":
        return bulk_update_tags(event)

    # Route: DELETE /media/files
    if route_key == "DELETE /media/files":
        return delete_files(event)

    # Route: POST /media/search-by-query-upload
    if route_key == "POST /media/search-by-query-upload":
        return search_by_query_upload(event)

    # Route: GET /media/{file_id}/urls
    if route_key == "GET /media/{file_id}/urls":
        return get_urls_for_file(file_id)

    # Route: GET /media/{file_id}
    if route_key == "GET /media/{file_id}":
        return get_file_by_id(file_id)

    # Route: GET /media/by-tag/{tag_name}
    if route_key == "GET /media/by-tag/{tag_name}":
        return query_files_by_tag(tag_name)

    # Fallback support if routeKey is not available or differs.
    raw_path = event.get("rawPath", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "")

    # Fallback: /media/tag-summary
    if raw_path.endswith("/media/tag-summary"):
        return get_tag_summary()

    # Fallback: /media/search-by-tags
    if method == "POST" and raw_path.endswith("/media/search-by-tags"):
        return query_files_by_tag_counts(event)

    # Fallback: /media/search-by-thumbnail
    if method == "POST" and raw_path.endswith("/media/search-by-thumbnail"):
        return search_by_thumbnail_url(event)

    # Fallback: /media/bulk-tags
    if method == "POST" and raw_path.endswith("/media/bulk-tags"):
        return bulk_update_tags(event)

    # Fallback: /media/files
    if method == "DELETE" and raw_path.endswith("/media/files"):
        return delete_files(event)

    # Fallback: /media/search-by-query-upload
    if method == "POST" and raw_path.endswith("/media/search-by-query-upload"):
        return search_by_query_upload(event)

    # Fallback: /media/by-tag/{tag_name}
    if raw_path.startswith("/media/by-tag/") and tag_name:
        return query_files_by_tag(tag_name)

    # Fallback: /media/{file_id}/urls
    if raw_path.startswith("/media/") and raw_path.endswith("/urls") and file_id:
        return get_urls_for_file(file_id)

    # Fallback: /media/{file_id}
    if raw_path.startswith("/media/") and file_id:
        return get_file_by_id(file_id)

    return build_response(404, {
        "message": "Unsupported route",
        "routeKey": route_key,
        "rawPath": raw_path
    })

