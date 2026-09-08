"""Non-biometric image fingerprints. No face recognition or external uploads."""

import hashlib
import io
import warnings
from typing import Annotated
from uuid import UUID

import imagehash
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from PIL import Image

from backend.api.dependencies import get_repository
from backend.db.models import ImageArtifact
from backend.db.repositories import PostgresInvestigationRepository

router = APIRouter(prefix="/api/searches", tags=["images"])


def fingerprint(data):
    if len(data) > 5_000_000:
        raise ValueError("Image exceeds 5 MB")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Use JPEG, PNG, or WebP")
            if picture.width * picture.height > 16_000_000:
                raise ValueError("Image exceeds 16 megapixels")
            picture.load()
            return dict(
                sha256=hashlib.sha256(data).hexdigest(),
                perceptual_hash=str(imagehash.phash(picture.convert("RGB"))),
                width=picture.width,
                height=picture.height,
            )


@router.post("/{search_id}/images", status_code=201)
async def upload_image(
    search_id: UUID,
    file: UploadFile,
    repository: Annotated[PostgresInvestigationRepository, Depends(get_repository)],
):
    if await repository.get_search(search_id) is None:
        raise HTTPException(404, "search not found")
    try:
        data = await file.read(5_000_001)
        values = fingerprint(data)
    except Exception as exc:
        raise HTTPException(422, "Invalid or oversized image") from exc
    finally:
        await file.close()
    artifact = ImageArtifact(
        **values,
        metadata_json={
            "search_id": str(search_id),
            "source": "USER_SUPPLIED",
            "meaning": "Image similarity only; not identity evidence",
            "retention": "Raw bytes discarded immediately; only fingerprints retained",
        },
    )
    repository.session.add(artifact)
    await repository.session.flush()
    return {
        "id": str(artifact.id),
        **values,
        "face_recognition": "DISABLED",
        "raw_image_retained": False,
    }
