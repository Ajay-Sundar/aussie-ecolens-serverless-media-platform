from utils import calculate_checksum, create_thumbnail, build_file_metadata


def main():
    image_path = "images/Alectura_lathami_1.JPG"

    checksum = calculate_checksum(image_path)

    thumbnail_path = create_thumbnail(
        image_path=image_path,
        output_path="thumbnails/Alectura_lathami_1_thumb.jpg",
        max_size=(300, 300),
        quality=75
    )

    metadata = build_file_metadata(
        file_id="test-file-001",
        original_path=image_path,
        thumbnail_path=thumbnail_path,
        file_type="image",
        checksum=checksum,
        tags={
            "Alectura_lathami": 1
        }
    )

    print(metadata)


if __name__ == "__main__":
    main()