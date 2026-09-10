"""Whole-image duplicate detection. No face detection, embeddings or identity inference.

All bytes and fingerprints are request-local. Results never enter the evidence ledger.
"""

import asyncio
import hashlib
import io
import warnings
from datetime import UTC, datetime

import imagehash
from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

from backend.connectors.safe_http import fetch_public

MAX_BYTES = 5_000_000
MAX_AVATARS = 32
MAX_SECONDS = 45
METHOD_VERSION = "whole-image-reuse-v2"  # v2: added colorhash, whash, crop_resistant_hash


def fingerprint(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Empty image or image exceeds 5 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Use JPEG, PNG or WebP")
                if source.width * source.height > 16_000_000:
                    raise ValueError("Image exceeds 16 megapixels")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Animated images are unsupported")
                source.load()
                picture = ImageOps.exif_transpose(source).convert("RGBA")
                pixels = hashlib.sha256(picture.tobytes()).hexdigest()
                background = Image.new("RGBA", picture.size, "white")
                background.alpha_composite(picture)
                rgb = background.convert("RGB")
                thumbnail = rgb.resize((32, 32), Image.Resampling.LANCZOS)
                return {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "pixels": pixels,
                    "size": picture.size,
                    # Five complementary perceptual-hash algorithms:
                    # phash  — DCT-based; good for resizes and JPEG recompression
                    # dhash  — gradient-based; fast, catches contrast changes
                    # colorhash — colour-distribution; catches palette-identical images
                    # whash  — wavelet-based; better at crop detection
                    # crop_resistant_hash — multi-segment; survives heavy cropping
                    "phash": str(imagehash.phash(rgb)),
                    "dhash": str(imagehash.dhash(rgb)),
                    "colorhash": str(imagehash.colorhash(rgb, binbits=3)),
                    "whash": str(imagehash.whash(rgb)),
                    "crop_resistant_hash": str(imagehash.crop_resistant_hash(rgb)),
                    "thumbnail": thumbnail.tobytes(),
                    "variation": max(ImageStat.Stat(thumbnail).stddev),
                }
    except (
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
        UnidentifiedImageError,
    ) as exc:
        raise ValueError("Unsafe or invalid image") from exc


def compare(reference, candidate):
    if reference["sha256"] == candidate["sha256"]:
        return {
            "status": "EXACT_FILE",
            "message": "Same image appears on this profile.",
            "method": "sha256",
        }
    if reference["size"] == candidate["size"] and reference["pixels"] == candidate["pixels"]:
        return {
            "status": "SAME_PIXELS",
            "message": "Same image appears on this profile.",
            "method": "decoded-pixel-sha256",
        }
    if min(reference["variation"], candidate["variation"]) < 12:
        return {"status": "INCONCLUSIVE", "message": "Too little visual detail for reuse matching."}

    def ham(key):
        try:
            return (int(reference[key], 16) ^ int(candidate[key], 16)).bit_count()
        except (KeyError, ValueError):
            return 999

    phash_distance = ham("phash")
    dhash_distance = ham("dhash")
    colorhash_distance = ham("colorhash")
    whash_distance = ham("whash")

    aspect_a = reference["size"][0] / reference["size"][1]
    aspect_b = candidate["size"][0] / candidate["size"][1]
    mse = sum(
        (a - b) ** 2 for a, b in zip(reference["thumbnail"], candidate["thumbnail"], strict=True)
    ) / (32 * 32 * 3 * 255**2)

    # Require at least 3 of 4 hash algorithms to agree (more robust than the v1 2-of-2 check)
    near_votes = sum([
        phash_distance <= 6,
        dhash_distance <= 6,
        colorhash_distance <= 4,
        whash_distance <= 8,
        mse <= 0.008,
    ])
    near = near_votes >= 3 and abs(aspect_a / aspect_b - 1) <= 0.05

    return {
        "status": "POSSIBLE_REUSE" if near else "NO_REUSE_DETECTED",
        "message": (
            "Possible resized or recompressed copy; review the source image."
            if near
            else "No image reuse detected; this says nothing about ownership."
        ),
        "method": "phash+dhash+colorhash+whash+thumbnail-mse+aspect",
        "phash_distance": phash_distance,
        "dhash_distance": dhash_distance,
        "colorhash_distance": colorhash_distance,
        "whash_distance": whash_distance,
        "thumbnail_mse": round(mse, 6),
        "near_vote_count": near_votes,
    }


async def compare_profiles(reference, profiles):
    semaphore = asyncio.Semaphore(4)
    rows, urls = [], {}
    for profile in profiles:
        row = {
            "profile_id": str(profile.id),
            "platform": profile.platform,
            "username": profile.username,
            "profile_url": profile.canonical_url,
            "image_url": profile.avatar_url,
            "source_observation_ids": list(profile.source_observation_ids),
            "status": "NO_PUBLIC_IMAGE",
            "message": "No public avatar collected in this search.",
        }
        rows.append(row)
        if profile.avatar_url:
            if profile.avatar_url not in urls and len(urls) >= MAX_AVATARS:
                row.update(status="LIMIT_REACHED", message="Image fetch budget reached.")
            else:
                urls.setdefault(profile.avatar_url, []).append(row)
                row.update(
                    status="TIMEOUT", message="Image check did not finish within the budget."
                )

    async def check(url, targets):
        async with semaphore:
            try:
                async with asyncio.timeout(15):
                    data, final_url, _ = await fetch_public(
                        url,
                        max_bytes=MAX_BYTES,
                        allowed_types=("image/jpeg", "image/png", "image/webp"),
                    )
                    candidate = await asyncio.to_thread(fingerprint, data)
                    del data
                    outcome = {**compare(reference, candidate), "fetched_url": final_url}
            except TimeoutError:
                outcome = {"status": "TIMEOUT", "message": "Public image request timed out."}
            except Exception:
                outcome = {
                    "status": "UNAVAILABLE",
                    "message": "Image blocked, inaccessible, unsafe, oversized or unsupported.",
                }
            for row in targets:
                row.update(outcome)

    try:
        async with asyncio.timeout(MAX_SECONDS):
            await asyncio.gather(*(check(url, targets) for url, targets in urls.items()))
    except TimeoutError:
        pass
    checked = sum(
        row["status"]
        in {"EXACT_FILE", "SAME_PIXELS", "POSSIBLE_REUSE", "NO_REUSE_DETECTED", "INCONCLUSIVE"}
        for row in rows
    )
    return {
        "items": rows,
        "checked_at": datetime.now(UTC).isoformat(),
        "checked": checked,
        "method_version": METHOD_VERSION,
        "status": "COMPLETE" if checked == len(rows) and rows else "PARTIAL",
        "identity_scores_changed": False,
        "face_recognition": "DISABLED",
        "raw_image_retained": False,
        "fingerprints_retained": False,
        "limits": {"unique_images": MAX_AVATARS, "seconds": MAX_SECONDS},
        "limitations": [
            "Image reuse is not proof of identity or account ownership; images can be copied.",
            "Only avatars observed in this search are checked, not the whole internet.",
            "Different photos of the same person will not match; crops and edits may not match.",
            "Near-duplicate thresholds are conservative heuristics, not calibrated probabilities.",
            "Nothing is saved; request-local image data is released after use.",
        ],
    }
