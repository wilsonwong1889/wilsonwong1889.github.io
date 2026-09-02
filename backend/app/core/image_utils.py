import io

from fastapi import HTTPException, UploadFile
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

# Decoded-pixel ceiling, checked before any pixels are allocated. The byte limit
# above does not bound this: a heavily compressed image can sit well under 40 MB
# on disk and still expand to gigabytes in memory, which is enough to exhaust a
# 512 MB instance. 80 megapixels is far beyond any real camera upload.
MAX_IMAGE_PIXELS = 80_000_000

# Pillow's own backstop. It only *warns* between one and two times this value,
# so it is a second line of defence behind the explicit check below, not the
# primary one.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

_READ_CHUNK_BYTES = 512 * 1024


async def read_upload_within_limit(upload: UploadFile, max_bytes: int = MAX_PHOTO_BYTES) -> bytes:
    """Read an upload, refusing anything past the limit as it streams.

    ``await upload.read()`` with no argument materialises the entire body first
    and only then hands it to a size check, so a multi-gigabyte post exhausts
    memory before the limit is ever consulted. Reading in chunks caps the damage
    at the limit plus one chunk.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            limit_mb = max_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=f"Photo must be {limit_mb} MB or smaller.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


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
        # Image.open reads the header only, so the declared dimensions are known
        # before a single pixel is allocated. Reject oversized images here rather
        # than discovering the problem partway through decoding them.
        width, height = img.size
        if width * height > MAX_IMAGE_PIXELS:
            raise HTTPException(
                status_code=400,
                detail="That image is too large to process. Upload a photo under 80 megapixels.",
            )
        img.load()
    except Image.DecompressionBombError:
        raise HTTPException(
            status_code=400,
            detail="That image is too large to process. Upload a photo under 80 megapixels.",
        )
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
