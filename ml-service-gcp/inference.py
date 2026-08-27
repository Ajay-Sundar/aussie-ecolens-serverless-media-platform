import json
import os
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np
import requests
import torch
import torchvision.transforms as transforms
from PIL import Image
from megadetector.detection import run_detector_batch


# Store model paths in constants so they can be changed easily later.
MD_MODEL_PATH = "models/mdv5a.pt"
SPECIES_MODEL_PATH = "models/model.pt"

# Set the confidence threshold for accepting animal detections.
DETECTION_CONFIDENCE_THRESHOLD = 0.05

# Set the crop size expected by the species classifier.
SNIP_SIZE = 600

# Define how many frames to extract from videos.
# The assignment asks us to extract 1 image per second instead of all frames.
VIDEO_FRAME_INTERVAL_SECONDS = 1

# Define the class labels supported by the species classifier.
CLASSES = [
    "Alectura_lathami", "Antechinus_agilis", "Bos_taurus", "Burhinus_grallarius",
    "Canis_familiaris", "Chalcophaps_longirostris", "Colluricincla_harmonica",
    "Corcorax_melanorhamphos", "Dacelo_novaeguineae", "Dama_dama",
    "Eopsaltria_australis", "Felis_catus", "Geopelia_humeralis",
    "Gymnorhina_tibicen", "Homo_sapiens", "Isoodon_macrourus",
    "Lepus_europaeus", "Macropus_giganteus", "Menura_novaehollandiae",
    "Mus_musculus", "Oryctolagus_cuniculus", "Perameles_nasuta",
    "Pitta_versicolor", "Rattus", "Rattus_fuscipes", "Rattus_rattus",
    "Strepera_graculina", "Sus_scrofa", "Tachyglossus_aculeatus",
    "Thylogale_stigmatica", "Trichosurus_caninus", "Trichosurus_cunninghami",
    "Trichosurus_vulpecula", "Varanus_varius", "Vombatus_ursinus",
    "Vulpes_vulpes", "Wallabia_bicolor", "Canis_dingo", "Capra_hircus",
    "Casuarius_casuarius", "Heteromyias_cinereifrons", "Hypsiprymnodon_moschatus",
    "Megapodius_reinwardt", "Notamacropus_rufogriseus", "Orthonyx_spaldingii",
    "Uromys_caudimaculatus"
]


def get_device():
    # Cloud Run will use CPU unless GPU is explicitly configured.
    return "cpu"


# Load the device once when the container starts.
DEVICE = get_device()

# Define the image transform used before species classification.
TRANSFORM = transforms.Compose([
    transforms.Resize((480, 480)),
    transforms.ToTensor(),
])


def load_species_model():
    # Check that the species model exists inside the container.
    if not os.path.exists(SPECIES_MODEL_PATH):
        raise FileNotFoundError(f"Species model not found: {SPECIES_MODEL_PATH}")

    # Load the trained species classifier on CPU.
    model = torch.load(SPECIES_MODEL_PATH, map_location=DEVICE, weights_only=False)

    # Switch the model to inference mode.
    model.eval()

    # Move the model to the selected device.
    model.to(DEVICE)

    # Return the loaded model so predictions can reuse it.
    return model


# Load the species model once at container startup so each request is faster.
SPECIES_MODEL = load_species_model()


def download_file(file_url, output_path, timeout=300):
    # Download a file from the pre-signed URL sent by AWS Lambda.
    # This works for both images and videos.
    with requests.get(file_url, stream=True, timeout=timeout) as response:
        # Raise an exception if the download failed.
        response.raise_for_status()

        # Save the downloaded content in chunks to avoid loading large videos fully into memory.
        with open(output_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)


def download_image(image_url, output_path):
    # Keep this wrapper so the existing image code remains easy to understand.
    download_file(image_url, output_path, timeout=60)


def run_megadetector(image_path):
    # Check that the MegaDetector model exists inside the container.
    if not os.path.exists(MD_MODEL_PATH):
        raise FileNotFoundError(f"MegaDetector model not found: {MD_MODEL_PATH}")

    # Run MegaDetector on the single downloaded image.
    detections = run_detector_batch.load_and_run_detector_batch(
        image_file_names=[image_path],
        model_file=MD_MODEL_PATH
    )

    # Return the first detection result because we process one image at a time.
    return detections[0]


def crop_detected_animals(detection_result, crop_dir):
    # Create the crop output directory if it does not exist.
    Path(crop_dir).mkdir(parents=True, exist_ok=True)

    # Get the image path from the MegaDetector result.
    image_path = detection_result["file"]

    # Open the original image for cropping.
    image = Image.open(image_path).convert("RGB")

    # Get image dimensions.
    width, height = image.size

    # Store paths of all cropped animal images.
    crop_paths = []

    # Loop through all detections returned by MegaDetector.
    for index, detection in enumerate(detection_result.get("detections", [])):
        # Only keep animal detections. MegaDetector category "1" means animal.
        if detection.get("category") != "1":
            continue

        # Skip detections below the confidence threshold.
        if float(detection.get("conf", 0)) < DETECTION_CONFIDENCE_THRESHOLD:
            continue

        # Read the normalized bounding box values.
        x, y, w, h = detection["bbox"]

        # Convert normalized coordinates into pixel coordinates.
        left = int(x * width)
        top = int(y * height)
        right = int((x + w) * width)
        bottom = int((y + h) * height)

        # Clamp coordinates so invalid boxes do not break cropping.
        left = max(0, left)
        top = max(0, top)
        right = min(width, right)
        bottom = min(height, bottom)

        # Skip invalid boxes.
        if right <= left or bottom <= top:
            continue

        # Crop the detected animal region.
        crop = image.crop((left, top, right, bottom))

        # Resize the crop to the classifier input crop size.
        resized_crop = crop.resize((SNIP_SIZE, SNIP_SIZE), Image.BILINEAR)

        # Build a crop file path.
        crop_path = os.path.join(crop_dir, f"crop_{index}.jpg")

        # Save the crop to disk.
        resized_crop.save(crop_path)

        # Track the crop path for classification.
        crop_paths.append(crop_path)

    # Return all saved crop paths.
    return crop_paths


@torch.no_grad()
def classify_crop(crop_path):
    # Open the crop image.
    image = Image.open(crop_path).convert("RGB")

    # Apply the same transform used in the local classifier.
    tensor = TRANSFORM(image)

    # Add batch dimension.
    tensor = tensor.unsqueeze(0)

    # Change tensor layout from B,C,H,W to B,H,W,C because the provided model expects that layout.
    tensor = tensor.permute(0, 2, 3, 1)

    # Move tensor to the selected device.
    tensor = tensor.to(DEVICE)

    # Run the species classifier.
    logits = SPECIES_MODEL(tensor)

    # Convert logits to probabilities.
    probabilities = torch.softmax(logits, dim=1)[0].cpu().numpy()

    # Find the highest-confidence class.
    best_index = int(np.argmax(probabilities))

    # Return the predicted species and confidence.
    return {
        "species": CLASSES[best_index],
        "confidence": float(probabilities[best_index])
    }


def count_species_tags(predictions, min_confidence=0.5):
    # Store species counts in a dictionary.
    tags = {}

    # Count only predictions above the confidence threshold.
    for prediction in predictions:
        # Skip low-confidence predictions.
        if prediction["confidence"] < min_confidence:
            continue

        # Get the species label.
        species = prediction["species"]

        # Increment the species count.
        tags[species] = tags.get(species, 0) + 1

    # Return the species count map.
    return tags


def predict_species_from_local_image(image_path, working_dir):
    # Create a crop directory for this specific image/frame.
    crop_dir = os.path.join(working_dir, f"crops_{Path(image_path).stem}")

    # Run MegaDetector on the image.
    detection_result = run_megadetector(image_path)

    # Crop all detected animals.
    crop_paths = crop_detected_animals(detection_result, crop_dir)

    # If no animals are detected, return an empty list of predictions.
    if not crop_paths:
        return []

    # Classify every cropped animal image.
    predictions = [classify_crop(crop_path) for crop_path in crop_paths]

    # Return raw predictions so image and video paths can aggregate consistently.
    return predictions


def predict_species_from_url(image_url):
    # Create a temporary folder so each request is isolated.
    temp_dir = tempfile.mkdtemp(prefix="aussie_ecolens_image_")

    try:
        # Define temporary path for the downloaded image.
        image_path = os.path.join(temp_dir, "input_image.jpg")

        # Download the image from AWS using the pre-signed URL.
        download_image(image_url, image_path)

        # Run the existing local-image prediction pipeline.
        predictions = predict_species_from_local_image(image_path, temp_dir)

        # Convert predictions into species tag counts.
        tags = count_species_tags(predictions)

        # Return the final tag count dictionary.
        return tags

    finally:
        # Always remove the temporary folder after processing.
        shutil.rmtree(temp_dir, ignore_errors=True)


def extract_one_frame_per_second(video_path, frames_dir):
    # Create the directory where extracted video frames will be saved.
    Path(frames_dir).mkdir(parents=True, exist_ok=True)

    # Open the downloaded video using OpenCV.
    video_capture = cv2.VideoCapture(video_path)

    # If OpenCV cannot open the video, fail clearly.
    if not video_capture.isOpened():
        raise ValueError("Could not open video file for frame extraction")

    # Read the frames-per-second value from the video metadata.
    fps = video_capture.get(cv2.CAP_PROP_FPS)

    # Some videos may not expose FPS correctly. Use a safe fallback.
    if not fps or fps <= 0:
        fps = 1

    # Read total frame count so we know when to stop.
    total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))

    # If frame count is missing, still attempt sequential extraction.
    frame_paths = []
    second = 0

    while True:
        # Calculate the target frame index for this second.
        target_frame_index = int(second * fps * VIDEO_FRAME_INTERVAL_SECONDS)

        # Stop if we know the total frame count and the target is beyond the video.
        if total_frames > 0 and target_frame_index >= total_frames:
            break

        # Jump to the target frame.
        video_capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame_index)

        # Read the selected frame.
        success, frame = video_capture.read()

        # If no frame could be read, stop extraction.
        if not success:
            break

        # Convert OpenCV BGR frame to RGB because PIL/image models expect RGB-like images.
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Save the frame as a JPEG file.
        frame_path = os.path.join(frames_dir, f"frame_{second:05d}.jpg")
        Image.fromarray(frame_rgb).save(frame_path, "JPEG", quality=90)

        # Track the saved frame path.
        frame_paths.append(frame_path)

        # Move to the next second.
        second += 1

    # Release the video handle.
    video_capture.release()

    # Return all extracted frame image paths.
    return frame_paths


def predict_species_from_video_url(video_url):
    # Create a temporary folder so each video request is isolated.
    temp_dir = tempfile.mkdtemp(prefix="aussie_ecolens_video_")

    try:
        # Define temporary paths for the downloaded video and extracted frames.
        video_path = os.path.join(temp_dir, "input_video.mp4")
        frames_dir = os.path.join(temp_dir, "frames")

        # Download the video from AWS using the pre-signed URL.
        download_file(video_url, video_path, timeout=300)

        # Extract exactly one frame per second, as required by the assignment.
        frame_paths = extract_one_frame_per_second(video_path, frames_dir)

        # If no frames could be extracted, return no tags.
        if not frame_paths:
            return {}

        # Store predictions from all extracted frames.
        all_predictions = []

        # Run the existing image model pipeline on each extracted frame.
        for frame_path in frame_paths:
            frame_predictions = predict_species_from_local_image(frame_path, temp_dir)
            all_predictions.extend(frame_predictions)

        # Convert all frame predictions into aggregated species tag counts.
        tags = count_species_tags(all_predictions)

        # Return the final video-level tag map.
        return tags

    finally:
        # Always remove the temporary folder after processing.
        shutil.rmtree(temp_dir, ignore_errors=True)
