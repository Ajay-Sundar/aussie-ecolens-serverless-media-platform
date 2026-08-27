from pathlib import Path
from typing import Dict, List

import json
import os
from PIL import Image
from megadetector.detection import run_detector_batch


def list_image_files(input_dir: str) -> List[str]:
    input_path = Path(input_dir)

    image_files = []

    for file_path in input_path.iterdir():
        if file_path.name.startswith("."):
            continue

        if file_path.suffix.lower() in [".jpg", ".jpeg", ".png"]:
            image_files.append(str(file_path))

    return image_files


def run_megadetector(
    input_dir: str = "images",
    model_path: str = "mdv5a.pt",
    output_file: str = "mg_detections.json"
) -> List[Dict]:
    image_files = list_image_files(input_dir)

    print(f"Running MegaDetector on {len(image_files)} images...")

    data = run_detector_batch.load_and_run_detector_batch(
        image_file_names=image_files,
        model_file=model_path
    )

    with open(output_file, "w") as file:
        json.dump(data, file)

    return data


def crop_detected_animals(
    detections: List[Dict],
    output_dir: str = "cropped_images",
    confidence_threshold: float = 0.05,
    crop_size: int = 600
) -> List[str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cropped_files = []

    for entry in detections:
        img_path = entry["file"]

        if not Path(img_path).exists():
            continue

        img = Image.open(img_path).convert("RGB")
        width, height = img.size

        crop_num = 0

        for detection in entry["detections"]:
            confidence = detection["conf"]
            category = detection["category"]

            if category != "1":
                continue

            if confidence < confidence_threshold:
                continue

            x, y, w, h = detection["bbox"]

            left = int(x * width)
            top = int(y * height)
            right = int((x + w) * width)
            bottom = int((y + h) * height)

            crop = img.crop((left, top, right, bottom))
            crop = crop.resize((crop_size, crop_size), Image.BILINEAR)

            out_name = f"{Path(img_path).stem}-{crop_num}{Path(img_path).suffix}"
            out_path = output_path / out_name

            crop.save(out_path)
            cropped_files.append(str(out_path))

            crop_num += 1

    return cropped_files