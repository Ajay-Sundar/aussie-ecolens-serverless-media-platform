from detector import run_megadetector, crop_detected_animals
from inference import generate_tags_from_crops


def main():
    detections = run_megadetector(
        input_dir="images",
        model_path="mdv5a.pt",
        output_file="mg_detections_pipeline.json"
    )

    crop_detected_animals(
        detections=detections,
        output_dir="cropped_images_pipeline",
        confidence_threshold=0.05,
        crop_size=600
    )

    tags = generate_tags_from_crops(
        crop_folder="cropped_images_pipeline",
        model_path="model.pt",
        min_confidence=0.5
    )

    print("Generated tags:")
    print(tags)


if __name__ == "__main__":
    main()