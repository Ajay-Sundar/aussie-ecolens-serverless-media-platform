from pathlib import Path
from typing import Dict, List, Optional
import json

def load_database(db_path: str = "local_media_db.json") -> List[Dict]:
    path = Path(db_path)

    if not path.exists():
        return []

    with open(path, "r") as file:
        return json.load(file)
    

def save_database(records: List[Dict], db_path: str = "local_media_db.json") -> None:
    with open(db_path, "w") as file:
        json.dump(records, file, indent=4)


def add_media_record(record: Dict, db_path: str = "local_media_db.json") -> Dict:
    records = load_database(db_path)

    records.append(record)

    save_database(records, db_path)

    return record


def search_by_species(
    species: str,
    db_path: str = "local_media_db.json"
) -> List[Dict]:
    records = load_database(db_path)

    results = []

    for record in records:
        tags = record.get("tags", {})

        if tags.get(species, 0) >= 1:
            results.append(record)

    return results


def search_by_tag_counts(
    query_tags: Dict[str, int],
    db_path: str = "local_media_db.json"
) -> List[Dict]:
    records = load_database(db_path)

    results = []

    for record in records:
        record_tags = record.get("tags", {})

        matches_all_tags = True

        for species, required_count in query_tags.items():
            actual_count = record_tags.get(species, 0)

            if actual_count < required_count:
                matches_all_tags = False
                break

        if matches_all_tags:
            results.append(record)

    return results


def search_by_thumbnail(
    thumbnail_path: str,
    db_path: str = "local_media_db.json"
) -> Optional[Dict]:
    records = load_database(db_path)

    for record in records:
        if record.get("thumbnail_path") == thumbnail_path:
            return record

    return None


def update_tags_for_files(
    file_ids: List[str],
    tags_to_modify: Dict[str, int],
    operation: int,
    db_path: str = "local_media_db.json"
) -> List[Dict]:
    records = load_database(db_path)

    updated_records = []

    for record in records:
        if record.get("file_id") not in file_ids:
            continue

        record_tags = record.get("tags", {})

        for species, count in tags_to_modify.items():
            if operation == 1:
                record_tags[species] = record_tags.get(species, 0) + count

            elif operation == 0:
                if species in record_tags:
                    record_tags[species] = record_tags[species] - count

                    if record_tags[species] <= 0:
                        del record_tags[species]

            else:
                raise ValueError("operation must be 1 for add or 0 for remove")

        record["tags"] = record_tags
        updated_records.append(record)

    save_database(records, db_path)

    return updated_records