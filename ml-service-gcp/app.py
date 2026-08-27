import os
from flask import Flask, request, jsonify

from inference import predict_species_from_url, predict_species_from_video_url


# Create the Flask application.
app = Flask(__name__)


def is_internal_request_authorized():
    # Read the expected internal API key from the Cloud Run environment variable.
    expected_api_key = os.environ.get("INTERNAL_API_KEY")

    # Read the API key sent by AWS Lambda in the request header.
    provided_api_key = request.headers.get("X-Internal-Api-Key")

    # If the environment variable is missing, fail closed for security.
    if not expected_api_key:
        return False

    # Only allow the request if the provided key exactly matches the expected key.
    return provided_api_key == expected_api_key


@app.route("/", methods=["GET"])
def health_check():
    # Return a simple health response so we can confirm Cloud Run is alive.
    # This route stays public because it only exposes health metadata, not ML inference.
    return jsonify({
        "message": "Aussie EcoLens GCP ML service is running",
        "status": "healthy",
        "model_mode": "real_ml",
        "supported_file_types": ["image", "video"],
        "predict_endpoint_protected": True
    })


@app.route("/predict", methods=["POST"])
def predict():
    # Reject direct/unauthorised requests that do not include the internal API key.
    if not is_internal_request_authorized():
        return jsonify({
            "message": "Unauthorized request to ML service",
            "status": "unauthorized"
        }), 401

    # Read the incoming JSON request body.
    request_data = request.get_json(silent=True)

    # If the request body is missing or invalid, return an error.
    if not request_data:
        return jsonify({
            "message": "Missing or invalid JSON body"
        }), 400

    # Extract the file_id sent from AWS Lambda.
    file_id = request_data.get("file_id")

    # Prefer media_url because it works for both images and videos.
    # Keep image_url as a fallback for backward compatibility with the old AWS Lambda payload.
    media_url = request_data.get("media_url") or request_data.get("image_url")

    # Read media metadata sent by AWS.
    file_type = request_data.get("file_type", "image")
    content_type = request_data.get("content_type", "image/jpeg")

    # Validate that all required fields are present.
    if not file_id or not media_url:
        return jsonify({
            "message": "Missing file_id or media_url/image_url"
        }), 400

    # Validate the file type before running ML.
    if file_type not in ["image", "video"]:
        return jsonify({
            "file_id": file_id,
            "message": "Unsupported file_type",
            "file_type": file_type,
            "content_type": content_type,
            "status": "prediction_failed"
        }), 400

    try:
        # Route the request to the correct ML pipeline.
        if file_type == "image":
            # Existing image ML pipeline.
            predicted_tags = predict_species_from_url(media_url)

        else:
            # Video ML pipeline:
            # download video, extract 1 frame per second,
            # run image model on each frame, and aggregate tags.
            predicted_tags = predict_species_from_video_url(media_url)

        # Return the prediction result using the contract expected by AWS Lambda.
        return jsonify({
            "file_id": file_id,
            "file_type": file_type,
            "content_type": content_type,
            "tags": predicted_tags,
            "model_version": "megadetector_mdv5a_species_model_pt",
            "status": "tagged"
        })

    except Exception as error:
        # Return a clear error message if ML inference fails.
        return jsonify({
            "file_id": file_id,
            "file_type": file_type,
            "content_type": content_type,
            "message": "ML prediction failed",
            "error": str(error),
            "status": "prediction_failed"
        }), 500


if __name__ == "__main__":
    # Cloud Run provides the PORT environment variable.
    # If running locally, default to port 8080.
    port = int(os.environ.get("PORT", 8080))

    # Start the Flask app and listen on all interfaces.
    app.run(host="0.0.0.0", port=port)
