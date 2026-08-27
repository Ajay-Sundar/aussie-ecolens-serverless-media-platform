from pipeline import process_single_image


def main():
    tags = process_single_image(
        image_path="images/Alectura_lathami_1.JPG",
        detector_model_path="mdv5a.pt",
        species_model_path="model.pt",
        temp_input_dir="temp_single_image_input",
        detection_output_file="mg_detections_single.json",
        crop_output_dir="cropped_images_single",
        detection_confidence_threshold=0.05,
        crop_size=600,
        classification_confidence_threshold=0.5
    )

    print("Generated tags:")
    print(tags)


if __name__ == "__main__":
    main()