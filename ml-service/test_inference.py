from inference import generate_tags_from_crops


def main():
    tags = generate_tags_from_crops(
        crop_folder="cropped_images",
        model_path="model.pt",
        min_confidence=0.5
    )

    print(tags)


if __name__ == "__main__":
    main()