from pipeline import process_image_folder


def main():
    tags = process_image_folder(
        input_dir="images",
        detector_model_path="mdv5a.pt",
        species_model_path="model.pt",
        detection_output_file="mg_detections_wrapper.json",
        crop_output_dir="cropped_images_wrapper",
        detection_confidence_threshold=0.05,
        crop_size=600,
        classification_confidence_threshold=0.5
    )

    print("Generated tags:")
    print(tags)


if __name__ == "__main__":
    main()