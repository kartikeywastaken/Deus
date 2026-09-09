"""Deterministic image test fixtures only; production always fetches real avatars."""

import io
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image, ImageDraw

from backend import image_reuse
from backend.api import images
from backend.api.dependencies import get_repository


def encoded(size=256, fmt="PNG", quality=90, alternate=False):
    image = Image.new("RGB", (size, size), "#deaf34")
    draw = ImageDraw.Draw(image)
    draw.rectangle((size // 8, size // 4, size // 2, size * 3 // 4), fill="navy")
    draw.ellipse((size // 2, size // 5, size * 7 // 8, size * 4 // 5), fill="red")
    if alternate:
        draw.polygon([(0, 0), (size, 0), (size, size)], fill="green")
    output = io.BytesIO()
    image.save(output, format=fmt, quality=quality)
    return output.getvalue()


def test_exact_pixels_and_resized_reuse():
    data = encoded()
    reference = image_reuse.fingerprint(data)
    assert image_reuse.compare(reference, reference)["status"] == "EXACT_FILE"
    assert (
        image_reuse.compare(reference, image_reuse.fingerprint(encoded(128)))["status"]
        == "POSSIBLE_REUSE"
    )
    assert (
        image_reuse.compare(reference, image_reuse.fingerprint(encoded(fmt="JPEG", quality=75)))[
            "status"
        ]
        == "POSSIBLE_REUSE"
    )
    other = image_reuse.fingerprint(encoded(alternate=True))
    assert image_reuse.compare(reference, other)["status"] == "NO_REUSE_DETECTED"
    other_encoding = io.BytesIO()
    with Image.open(io.BytesIO(data)) as picture:
        picture.save(other_encoding, format="PNG", compress_level=0)
    assert (
        image_reuse.compare(reference, image_reuse.fingerprint(other_encoding.getvalue()))["status"]
        == "SAME_PIXELS"
    )


def test_invalid_flat_animated_and_oversized_images():
    for data in [b"", b"not an image", b"x" * (image_reuse.MAX_BYTES + 1)]:
        with pytest.raises(ValueError):
            image_reuse.fingerprint(data)
    images_data = []
    for color in ["white", "black"]:
        output = io.BytesIO()
        Image.new("RGB", (40, 40), color).save(output, format="PNG")
        images_data.append(image_reuse.fingerprint(output.getvalue()))
    assert image_reuse.compare(*images_data)["status"] == "INCONCLUSIVE"
    for picture in [Image.new("RGB", (4001, 4000)), Image.new("RGB", (20, 20))]:
        output = io.BytesIO()
        picture.save(
            output,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGB", picture.size, "red")],
        )
        with pytest.raises(ValueError):
            image_reuse.fingerprint(output.getvalue())


def profile(url=None):
    return SimpleNamespace(
        id=uuid4(),
        platform="github",
        username="test-fixture",
        canonical_url="https://github.com/test-fixture",
        avatar_url=url,
        source_observation_ids=[str(uuid4())],
    )


async def test_search_scoped_fetch_dedup_and_missing_images(monkeypatch):
    calls = []
    data = encoded()

    async def fetch(url, **kwargs):
        calls.append(url)
        if "blocked" in url:
            raise ValueError("Do not leak upstream details")
        return data, url, "image/png"

    monkeypatch.setattr(image_reuse, "fetch_public", fetch)
    url = "https://example.com/avatar.png"
    result = await image_reuse.compare_profiles(
        image_reuse.fingerprint(data),
        [profile(url), profile(url), profile(), profile("https://example.com/blocked")],
    )
    assert len(calls) == 2
    assert [r["status"] for r in result["items"]] == [
        "EXACT_FILE",
        "EXACT_FILE",
        "NO_PUBLIC_IMAGE",
        "UNAVAILABLE",
    ]
    assert not result["identity_scores_changed"]
    assert not result["raw_image_retained"] and not result["fingerprints_retained"]
    assert image_reuse.fingerprint(data)["sha256"] not in str(result)


async def test_budget_timeout_and_private_destination():
    result = await image_reuse.compare_profiles(
        image_reuse.fingerprint(encoded()), [profile("https://127.0.0.1/avatar")]
    )
    assert result["items"][0]["status"] == "UNAVAILABLE"


async def test_image_limit_and_timeout(monkeypatch):
    import asyncio

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(image_reuse, "fetch_public", slow)
    monkeypatch.setattr(image_reuse, "MAX_SECONDS", 0.01)
    monkeypatch.setattr(image_reuse, "MAX_AVATARS", 1)
    result = await image_reuse.compare_profiles(
        image_reuse.fingerprint(encoded()),
        [profile("https://example.com/1"), profile("https://example.com/2")],
    )
    assert [r["status"] for r in result["items"]] == ["TIMEOUT", "LIMIT_REACHED"]


async def test_stateless_api_validation_and_no_database_writes():
    class ReadOnlyRepository:
        def __init__(self):
            self.session = self

        async def get_search(self, search_id):
            return object() if search_id == known_id else None

        async def list_profile_snapshots_for_search(self, search_id):
            return [profile()]

        async def rollback(self):
            pass

    known_id = uuid4()
    app = FastAPI()
    app.include_router(images.router)
    app.dependency_overrides[get_repository] = ReadOnlyRepository
    root = f"/api/searches/{known_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post(root + "/images")).status_code == 410
        assert (await client.post(root + "/image-matches", content=b"bad")).status_code == 415
        assert (
            await client.post(
                root + "/image-matches", content=b"bad", headers={"Content-Type": "image/png"}
            )
        ).status_code == 422
        assert (
            await client.post(
                root + "/image-matches",
                content=b"x" * 5000001,
                headers={"Content-Type": "image/png"},
            )
        ).status_code == 413
        assert (await client.post(f"/api/searches/{uuid4()}/image-matches")).status_code == 404
        response = await client.post(
            root + "/image-matches", content=encoded(), headers={"Content-Type": "image/png"}
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["items"][0]["status"] == "NO_PUBLIC_IMAGE"
        assert not images._active_searches
