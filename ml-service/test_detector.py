from detector import run_megadetector, crop_detected_animals


def main():
    detections = run_megadetector(
        input_dir="images",
        model_path="mdv5a.pt",
        output_file="mg_detections_test.json"
    )

    cropped_files = crop_detected_animals(
        detections=detections,
        output_dir="cropped_images_test",
        confidence_threshold=0.05,
        crop_size=600
    )

    print("Cropped files:")
    for cropped_file in cropped_files:
        print(cropped_file)


if __name__ == "__main__":
    main()