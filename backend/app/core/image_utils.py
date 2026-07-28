import io

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
import pillow_heif

pillow_heif.register_heif_opener()

# Every upload is re-encoded to JPEG, so we validate by actually decoding the
# image rather than trusting the filename extension (a real photo may arrive as
# .jfif, .avif, .gif, HEIC, or with no extension at all). The extension tuple is
# kept only as a hint and is no longer used to accept/reject uploads.
MAX_PHOTO_BYTES = 40 * 1024 * 1024  # 40 MB — room for modern phone / Retina photos
ACCEPTED_PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")

# Longest-edge cap (pixels) for stored photos — plenty for hero/card display
# while keeping files a sensible size for the web.
MAX_IMAGE_DIMENSION = 2560


def to_jpeg_bytes(file_bytes: bytes) -> bytes:
    """Validate an uploaded image and return normalized JPEG bytes.

    Accepts any image Pillow can decode (JPEG, PNG, WebP, HEIC/HEIF, GIF, BMP,
    TIFF, …), honors EXIF orientation, flattens transparency onto white, and
    downscales oversized images. Raises ``HTTPException(400)`` for empty,
    oversized, or unreadable uploads.
    """
    if not file_bytes:
        raise HTTPException(status_code=400, detail="The uploaded photo is empty.")
    if len(file_bytes) > MAX_PHOTO_BYTES:
        limit_mb = MAX_PHOTO_BYTES // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"Photo must be {limit_mb} MB or smaller.")

    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(
            status_code=400,
            detail="Could not read that file as an image. Upload a photo such as JPG, PNG, HEIC, or WebP.",
        )

    # Apply the camera/phone rotation stored in EXIF before metadata is dropped,
    # so portrait photos don't end up sideways.
    img = ImageOps.exif_transpose(img)

    # Flatten any transparency onto white so the JPEG isn't black where alpha was.
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    else:
        img = img.convert("RGB")

    if max(img.size) > MAX_IMAGE_DIMENSION:
        img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90, optimize=True)
    return out.getvalue()
