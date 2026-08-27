from pathlib import Path
from typing import Dict, Optional
import hashlib

from PIL import Image

def calculate_checksum(file_path: str) -> str:
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def create_thumbnail(
    image_path: str,
    output_path: str,
    max_size: tuple = (300, 300),
    quality: int = 75
) -> str:
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    image = Image.open(image_path).convert("RGB")
    image.thumbnail(max_size)

    image.save(output_file, "JPEG", quality=quality)

    return str(output_file)


def build_file_metadata(
    file_id: str,
    original_path: str,
    file_type: str,
    checksum: str,
    tags: Dict[str, int],
    thumbnail_path: Optional[str] = None
) -> Dict[str, object]:
    return {
        "file_id": file_id,
        "original_path": original_path,
        "thumbnail_path": thumbnail_path,
        "file_type": file_type,
        "checksum": checksum,
        "tags": tags
    }