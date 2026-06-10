from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError


THUMBNAIL_MAX_EDGE = 768
THUMBNAIL_QUALITY = 88
THUMBNAIL_EXTENSION = "jpg"


def create_image_thumbnail(
    source_path: Path,
    thumbnail_path: Path,
    *,
    max_edge: int = THUMBNAIL_MAX_EDGE,
    quality: int = THUMBNAIL_QUALITY,
) -> Path | None:
    try:
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            thumbnail = _flatten_for_jpeg(image)
            thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
            thumbnail.save(thumbnail_path, "JPEG", quality=quality, optimize=True)
            return thumbnail_path
    except (OSError, UnidentifiedImageError, ValueError):
        return None


def thumbnail_needs_refresh(
    source_path: Path,
    thumbnail_path: Path,
    *,
    max_edge: int = THUMBNAIL_MAX_EDGE,
) -> bool:
    if not thumbnail_path.exists():
        return True
    try:
        if thumbnail_path.stat().st_mtime < source_path.stat().st_mtime:
            return True
        with Image.open(source_path) as source, Image.open(thumbnail_path) as thumbnail:
            source = ImageOps.exif_transpose(source)
            expected_edge = min(max(source.size), max_edge)
            return max(thumbnail.size) != expected_edge
    except (OSError, UnidentifiedImageError, ValueError):
        return True


def _flatten_for_jpeg(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if "A" not in image.getbands():
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def output_thumbnail_filename(task_id: str, output_index: int) -> str:
    return f"{task_id}-image-{output_index}-thumb.{THUMBNAIL_EXTENSION}"


def input_thumbnail_filename(task_id: str, input_index: int) -> str:
    return f"{task_id}-input-{input_index:02d}-thumb.{THUMBNAIL_EXTENSION}"


def clean_thumbnail_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(record)
    for key in ("thumbnail_file", "thumbnail_url"):
        value = cleaned.get(key)
        if value is not None:
            cleaned[key] = str(value)
    return cleaned
