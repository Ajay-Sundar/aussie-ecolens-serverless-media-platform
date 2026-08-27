from typing import Dict
from pathlib import Path
import shutil

from detector import run_megadetector, crop_detected_animals
from inference import generate_tags_from_crops


def process_image_folder(
    input_dir: str = "images",
    detector_model_path: str = "mdv5a.pt",
    species_model_path: str = "model.pt",
    detection_output_file: str = "mg_detections_pipeline.json",
    crop_output_dir: str = "cropped_images_pipeline",
    detection_confidence_threshold: float = 0.05,
    crop_size: int = 600,
    classification_confidence_threshold: float = 0.5
) -> Dict[str, int]:
    detections = run_megadetector(
        input_dir=input_dir,
        model_path=detector_model_path,
        output_file=detection_output_file
    )

    crop_detected_animals(
        detections=detections,
        output_dir=crop_output_dir,
        confidence_threshold=detection_confidence_threshold,
        crop_size=crop_size
    )

    tags = generate_tags_from_crops(
        crop_folder=crop_output_dir,
        model_path=species_model_path,
        min_confidence=classification_confidence_threshold
    )

    return tags


def process_single_image(
    image_path: str,
    detector_model_path: str = "mdv5a.pt",
    species_model_path: str = "model.pt",
    temp_input_dir: str = "temp_single_image_input",
    detection_output_file: str = "mg_detections_single.json",
    crop_output_dir: str = "cropped_images_single",
    detection_confidence_threshold: float = 0.05,
    crop_size: int = 600,
    classification_confidence_threshold: float = 0.5
) -> Dict[str, int]:
    temp_dir = Path(temp_input_dir)
    crop_dir = Path(crop_output_dir)

    # Remove old temporary folders if they already exist
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    if crop_dir.exists():
        shutil.rmtree(crop_dir)

    temp_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(image_path)

    if not source_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    
    if source_path.suffix.lower() not in [".jpg", ".jpeg", ".png"]:
        raise ValueError(f"Unsupported image file type: {source_path.suffix}")

    temp_image_path = temp_dir / source_path.name

    shutil.copy2(source_path, temp_image_path)

    try:
        tags = process_image_folder(
            input_dir=str(temp_dir),
            detector_model_path=detector_model_path,
            species_model_path=species_model_path,
            detection_output_file=detection_output_file,
            crop_output_dir=crop_output_dir,
            detection_confidence_threshold=detection_confidence_threshold,
            crop_size=crop_size,
            classification_confidence_threshold=classification_confidence_threshold
        )

        return tags

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        if crop_dir.exists():
            shutil.rmtree(crop_dir)

        detection_file = Path(detection_output_file)
        if detection_file.exists():
            detection_file.unlink()