from pathlib import Path
from local_db import (
    add_media_record,
    load_database,
    search_by_species,
    search_by_tag_counts,
    search_by_thumbnail,
    update_tags_for_files,
)


def main():
    db_file = Path("local_media_db.json")
    if db_file.exists():
        db_file.unlink()

    record_1 = {
        "file_id": "test-file-001",
        "original_path": "images/Alectura_lathami_1.JPG",
        "thumbnail_path": "thumbnails/Alectura_lathami_1_thumb.jpg",
        "file_type": "image",
        "checksum": "checksum-001",
        "tags": {
            "Alectura_lathami": 1
        }
    }

    record_2 = {
        "file_id": "test-file-002",
        "original_path": "images/Bos_taurus_2.JPG",
        "thumbnail_path": "thumbnails/Bos_taurus_2_thumb.jpg",
        "file_type": "image",
        "checksum": "checksum-002",
        "tags": {
            "Bos_taurus": 8
        }
    }

    record_3 = {
        "file_id": "test-file-003",
        "original_path": "images/mixed_example.JPG",
        "thumbnail_path": "thumbnails/mixed_example_thumb.jpg",
        "file_type": "image",
        "checksum": "checksum-003",
        "tags": {
            "Bos_taurus": 2,
            "Canis_familiaris": 1
        }
    }

    add_media_record(record_1)
    add_media_record(record_2)
    add_media_record(record_3)

    print("All records:")
    print(load_database())

    print("\nSearch by species: Bos_taurus")
    print(search_by_species("Bos_taurus"))

    print("\nSearch by tag count: Bos_taurus >= 3")
    print(search_by_tag_counts({"Bos_taurus": 3}))

    print("\nSearch by tag count: Bos_taurus >= 2 AND Canis_familiaris >= 1")
    print(search_by_tag_counts({
        "Bos_taurus": 2,
        "Canis_familiaris": 1
    }))

    print("\nSearch by tag count: Bos_taurus >= 5 AND Canis_familiaris >= 1")
    print(search_by_tag_counts({
        "Bos_taurus": 5,
        "Canis_familiaris": 1
    }))

    print("\nSearch by thumbnail path:")
    thumbnail_result = search_by_thumbnail("thumbnails/Bos_taurus_2_thumb.jpg")
    print(thumbnail_result)

    if thumbnail_result:
        print("\nOriginal path for thumbnail:")
        print(thumbnail_result["original_path"])

    print("\nAdd manual tag: Canis_familiaris +1 to test-file-001")
    print(update_tags_for_files(
        file_ids=["test-file-001"],
        tags_to_modify={"Canis_familiaris": 1},
        operation=1
    ))

    print("\nRecords after adding manual tag:")
    print(load_database())

    print("\nRemove manual tag: Canis_familiaris -1 from test-file-001")
    print(update_tags_for_files(
        file_ids=["test-file-001"],
        tags_to_modify={"Canis_familiaris": 1},
        operation=0
    ))

    print("\nRecords after removing manual tag:")
    print(load_database())


if __name__ == "__main__":
    main()