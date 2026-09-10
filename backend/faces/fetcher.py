"""SSRF-safe avatar fetcher for face processing.

Wraps safe_http.fetch_public with image-appropriate limits and content-type
validation. All fetched bytes are request-local; nothing is stored here.
"""

from __future__ import annotations

from backend.connectors.safe_http import fetch_public

MAX_AVATAR_BYTES = 8_000_000  # 8 MB
AVATAR_TIMEOUT = 20           # seconds per image
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


async def fetch_avatar(url: str) -> bytes:
    """Fetch a public HTTPS avatar URL and return raw bytes.

    Raises:
        ValueError — if the URL is invalid or not HTTPS
        OSError    — on network/timeout error
        TypeError  — if content-type is not an allowed image type
    """
    data, final_url, content_type = await fetch_public(
        url,
        max_bytes=MAX_AVATAR_BYTES,
        allowed_types=ALLOWED_IMAGE_TYPES,
    )
    if content_type and not any(content_type.startswith(t) for t in ALLOWED_IMAGE_TYPES):
        raise TypeError(f"Unexpected content-type: {content_type!r}")
    return bytes(data)
