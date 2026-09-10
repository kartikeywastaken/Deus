"""Image ingestion pipeline: validate → decode → detect faces → embed → quality gate.

Handles both reference images (uploaded bytes) and candidate avatars (fetched URLs).
All face inference runs in asyncio.to_thread() to avoid blocking the event loop.

Multiple-face handling
----------------------
REFERENCE IMAGE:
  0 faces → raises NoFaceDetected
  1 face  → use it (face_index=0)
  N faces → returns MultipleDetectedFaces with all bboxes; caller selects face_index

PROFILE AVATAR:
  0 faces → returns status=NO_FACE
  1 face  → embed it
  N faces → embed the highest-confidence face; mark MULTIPLE_FACES in metadata
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import warnings
from dataclasses import dataclass, field
from typing import Any

import imagehash
import numpy as np
from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

from backend.faces.engine import (
    DetectedFace,
    FaceEngineError,
    MIN_DETECT_SCORE,
    MIN_FACE_AREA_FRACTION,
    get_engine_async,
)

# --------------------------------------------------------------------------- #
# Limits and constants
# --------------------------------------------------------------------------- #
MAX_UPLOAD_BYTES: int = 8_000_000       # 8 MB
MAX_IMAGE_PIXELS: int = 16_000_000      # 16 MP
MAX_IMAGE_WIDTH: int = 8_000
MAX_IMAGE_HEIGHT: int = 8_000
ALLOWED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP"})


# --------------------------------------------------------------------------- #
# Exception types
# --------------------------------------------------------------------------- #
class ImageValidationError(ValueError):
    """Raised when an image is invalid, unsafe or unsupported."""


class NoFaceDetected(ValueError):
    """No detectable face in the image."""


class MultipleDetectedFaces(ValueError):
    """Multiple faces found; caller must choose face_index."""

    def __init__(self, faces: list[DetectedFace]) -> None:
        super().__init__(f"{len(faces)} faces detected; choose one.")
        self.faces = faces


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ImageFingerprint:
    """Hashes and metadata extracted from image bytes (no face inference)."""

    sha256: str
    pixels_sha256: str               # hash of decoded RGBA pixel bytes
    phash: str                       # 64-bit perceptual hash (hex)
    dhash: str                       # 64-bit difference hash (hex)
    colorhash: str                   # 49-bit colour distribution hash (hex)
    whash: str                       # 64-bit wavelet hash (hex)
    crop_resistant_hash: str         # multi-segment crop-resistant hash (hex)
    width: int
    height: int
    format: str


@dataclass(slots=True)
class ProcessedFace:
    """One embedded face ready for comparison or persistence."""

    face_index: int
    bbox: tuple[float, float, float, float]
    detection_confidence: float
    quality_score: float
    face_area_fraction: float
    embedding: np.ndarray            # (512,) float32, L2-normalized
    image_fingerprint: ImageFingerprint
    multiple_faces_in_image: bool = False
    face_count: int = 1


@dataclass(slots=True)
class AvatarProcessingResult:
    """Result of processing a remote profile avatar."""

    status: str  # PROCESSED | NO_FACE | MULTIPLE_FACES | LOW_QUALITY | FETCH_FAILED | MODEL_UNAVAILABLE
    face: ProcessedFace | None = None
    fingerprint: ImageFingerprint | None = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Image fingerprinting (no face inference)
# --------------------------------------------------------------------------- #
def fingerprint_bytes(data: bytes | bytearray) -> tuple[ImageFingerprint, Image.Image]:
    """Validate, decode, and fingerprint raw image bytes.

    Returns the fingerprint AND the decoded PIL Image (RGB) for downstream use.
    The caller is responsible for closing/releasing the Image.

    Raises ImageValidationError on any problem.
    """
    if not data:
        raise ImageValidationError("Empty image data.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageValidationError(f"Image exceeds {MAX_UPLOAD_BYTES // 1_000_000} MB limit.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            raw = Image.open(io.BytesIO(bytes(data)))
            if raw.format not in ALLOWED_FORMATS:
                raise ImageValidationError(
                    f"Unsupported format '{raw.format}'. Use JPEG, PNG or WebP."
                )
            if raw.width > MAX_IMAGE_WIDTH or raw.height > MAX_IMAGE_HEIGHT:
                raise ImageValidationError(
                    f"Image dimensions {raw.width}×{raw.height} exceed {MAX_IMAGE_WIDTH}×{MAX_IMAGE_HEIGHT}."
                )
            if raw.width * raw.height > MAX_IMAGE_PIXELS:
                raise ImageValidationError("Image exceeds 16 MP limit.")
            if getattr(raw, "n_frames", 1) != 1:
                raise ImageValidationError("Animated images are not supported.")
            raw.load()
            img_format = raw.format or "UNKNOWN"

            # Strip EXIF orientation, convert to RGBA for canonical pixel hash
            rgba = ImageOps.exif_transpose(raw).convert("RGBA")
            pixel_hash = hashlib.sha256(rgba.tobytes()).hexdigest()

            # Flatten to RGB (white background) for perceptual hashing
            bg = Image.new("RGBA", rgba.size, "white")
            bg.alpha_composite(rgba)
            rgb = bg.convert("RGB")

            # Multi-algorithm perceptual hashing
            ph = str(imagehash.phash(rgb))
            dh = str(imagehash.dhash(rgb))
            ch = str(imagehash.colorhash(rgb, binbits=3))
            wh = str(imagehash.whash(rgb))
            crh = str(imagehash.crop_resistant_hash(rgb))

            fingerprint = ImageFingerprint(
                sha256=hashlib.sha256(bytes(data)).hexdigest(),
                pixels_sha256=pixel_hash,
                phash=ph,
                dhash=dh,
                colorhash=ch,
                whash=wh,
                crop_resistant_hash=crh,
                width=rgb.width,
                height=rgb.height,
                format=img_format,
            )
            return fingerprint, rgb

    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ImageValidationError("Possible decompression bomb — image rejected.") from exc
    except UnidentifiedImageError as exc:
        raise ImageValidationError("Cannot decode image; file may be corrupt or unsupported.") from exc
    except ImageValidationError:
        raise
    except Exception as exc:
        raise ImageValidationError(f"Image processing failed: {exc}") from exc


# --------------------------------------------------------------------------- #
# PIL-based EXIF extraction (no external tools required)
# --------------------------------------------------------------------------- #
def extract_exif_pil(data: bytes | bytearray) -> dict[str, Any]:
    """Extract EXIF metadata using PIL (always available, covers common tags).

    Returns a dict with human-readable tag names. GPS coordinates are decoded
    to decimal degrees when present. Returns an empty dict if no EXIF data.
    """
    from PIL import ExifTags

    try:
        with Image.open(io.BytesIO(bytes(data))) as img:
            raw_exif = img.getexif()
            if not raw_exif:
                return {}
            result: dict[str, Any] = {}
            for tag_id, value in raw_exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if tag_name == "GPSInfo":
                    gps_data = {}
                    for gps_tag_id, gps_value in value.items():  # type: ignore[union-attr]
                        gps_tag_name = ExifTags.GPSTAGS.get(gps_tag_id, str(gps_tag_id))
                        gps_data[gps_tag_name] = gps_value
                    result["GPSInfo"] = gps_data
                    # Decode to decimal degrees if complete
                    lat = _gps_to_decimal(gps_data.get("GPSLatitude"), gps_data.get("GPSLatitudeRef", "N"))
                    lon = _gps_to_decimal(gps_data.get("GPSLongitude"), gps_data.get("GPSLongitudeRef", "E"))
                    if lat is not None and lon is not None:
                        result["gps_decimal"] = {"lat": lat, "lon": lon}
                elif isinstance(value, bytes):
                    continue  # Skip binary blobs (thumbnail etc.)
                else:
                    try:
                        result[tag_name] = str(value)
                    except Exception:
                        pass
            return result
    except Exception:
        return {}


def _gps_to_decimal(dms: Any, ref: str) -> float | None:
    try:
        d, m, s = float(dms[0]), float(dms[1]), float(dms[2])
        decimal = d + m / 60 + s / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return round(decimal, 6)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# ExifTool-based extraction (optional, richer output)
# --------------------------------------------------------------------------- #
def extract_exif_exiftool(data: bytes | bytearray) -> dict[str, Any]:
    """Extract metadata via ExifTool if available; silently returns {} otherwise.

    ExifTool must be installed system-wide (brew install exiftool).
    PyExifTool wraps it as a subprocess — richer than PIL but external binary.
    """
    try:
        import exiftool
        import tempfile, os

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(bytes(data))
            tmp_path = tmp.name
        try:
            with exiftool.ExifToolHelper() as et:
                meta_list = et.get_metadata([tmp_path])
                if meta_list:
                    raw = meta_list[0]
                    # Strip ExifTool internal keys and file paths for privacy
                    return {
                        k: v
                        for k, v in raw.items()
                        if not k.startswith("SourceFile")
                        and "Directory" not in k
                        and "FileName" not in k
                        and not k.startswith("File:")
                    }
        finally:
            os.unlink(tmp_path)
    except Exception:
        return {}


def extract_exif(data: bytes | bytearray) -> dict[str, Any]:
    """Extract EXIF metadata, preferring ExifTool and falling back to PIL."""
    result = extract_exif_exiftool(data)
    if result:
        result["_source"] = "exiftool"
        return result
    pil_result = extract_exif_pil(data)
    if pil_result:
        pil_result["_source"] = "PIL"
    return pil_result


# --------------------------------------------------------------------------- #
# Face processing — reference image (caller-supplied bytes)
# --------------------------------------------------------------------------- #
async def process_reference_image(
    data: bytes | bytearray,
    *,
    face_index: int = 0,
) -> tuple[ProcessedFace, dict[str, Any]]:
    """Validate, fingerprint, detect, and embed a reference image.

    Returns:
        (ProcessedFace, exif_metadata)

    Raises:
        ImageValidationError — invalid image
        NoFaceDetected       — no face found
        MultipleDetectedFaces — multiple faces; caller should ask user to pick
        FaceEngineError      — model unavailable
    """
    # 1. Fingerprint + decode (CPU-bound but fast — run in thread)
    fingerprint, rgb_pil = await asyncio.to_thread(fingerprint_bytes, data)

    # 2. Extract EXIF (optional OSINT signal)
    exif = await asyncio.to_thread(extract_exif, data)

    # 3. Convert PIL → numpy RGB for InsightFace
    rgb_array = np.array(rgb_pil, dtype=np.uint8)

    # 4. Detect + embed faces
    engine = await get_engine_async()
    faces: list[DetectedFace] = await asyncio.to_thread(engine.analyse, rgb_array)

    usable = [
        f for f in faces
        if f.detection_confidence >= MIN_DETECT_SCORE
        and f.face_area_fraction >= MIN_FACE_AREA_FRACTION
    ]

    if not usable:
        raise NoFaceDetected(
            "No detectable face found. "
            "Ensure the image is unobstructed, well-lit and at least 100×100 px."
        )

    if len(usable) > 1 and face_index == 0:
        # Return all faces — let the caller/user choose
        raise MultipleDetectedFaces(usable)

    chosen = usable[min(face_index, len(usable) - 1)]

    processed = ProcessedFace(
        face_index=chosen.face_index,
        bbox=chosen.bbox,
        detection_confidence=chosen.detection_confidence,
        quality_score=chosen.quality_score,
        face_area_fraction=chosen.face_area_fraction,
        embedding=chosen.embedding,
        image_fingerprint=fingerprint,
        multiple_faces_in_image=len(usable) > 1,
        face_count=len(usable),
    )
    return processed, exif


# --------------------------------------------------------------------------- #
# Face processing — remote profile avatar (fetched bytes)
# --------------------------------------------------------------------------- #
async def process_avatar_bytes(data: bytes) -> AvatarProcessingResult:
    """Process fetched avatar bytes.  Never raises — returns structured status."""
    try:
        fingerprint, rgb_pil = await asyncio.to_thread(fingerprint_bytes, data)
    except ImageValidationError as exc:
        return AvatarProcessingResult(
            status="UNSUPPORTED_FORMAT",
            message=str(exc),
        )

    try:
        engine = await get_engine_async()
    except FaceEngineError as exc:
        return AvatarProcessingResult(
            status="MODEL_UNAVAILABLE",
            message=str(exc),
        )

    rgb_array = np.array(rgb_pil, dtype=np.uint8)
    try:
        faces: list[DetectedFace] = await asyncio.to_thread(engine.analyse, rgb_array)
    except Exception as exc:
        return AvatarProcessingResult(
            status="INFERENCE_FAILED",
            message=str(exc),
        )

    usable = [
        f for f in faces
        if f.detection_confidence >= MIN_DETECT_SCORE
        and f.face_area_fraction >= MIN_FACE_AREA_FRACTION
    ]

    if not usable:
        return AvatarProcessingResult(
            status="NO_FACE",
            fingerprint=fingerprint,
            message="No usable face detected in this candidate image.",
        )

    chosen = usable[0]  # Highest-confidence face
    multiple = len(usable) > 1

    if chosen.quality_score < 0.3:
        return AvatarProcessingResult(
            status="LOW_QUALITY",
            fingerprint=fingerprint,
            message="Detected face is too low quality for reliable comparison.",
            metadata={"quality_score": chosen.quality_score, "face_count": len(usable)},
        )

    processed = ProcessedFace(
        face_index=chosen.face_index,
        bbox=chosen.bbox,
        detection_confidence=chosen.detection_confidence,
        quality_score=chosen.quality_score,
        face_area_fraction=chosen.face_area_fraction,
        embedding=chosen.embedding,
        image_fingerprint=fingerprint,
        multiple_faces_in_image=multiple,
        face_count=len(usable),
    )

    return AvatarProcessingResult(
        status="PROCESSED",
        face=processed,
        fingerprint=fingerprint,
        metadata={
            "face_count": len(usable),
            "multiple_faces": multiple,
            "quality_score": chosen.quality_score,
        },
    )
