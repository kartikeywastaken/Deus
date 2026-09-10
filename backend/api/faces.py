"""Face comparison API endpoints.

POST /api/searches/{search_id}/reference-image
    Upload a reference image for face comparison against discovered candidate avatars.
    Stores an ImageArtifact, persists face embedding, then compares against all
    candidate profile avatars already discovered in the search.

GET /api/searches/{search_id}/face-matches
    Return the most recent face-match results for a search.

SECURITY NOTE:
    All comparisons are scoped to the current investigation. No cross-investigation
    biometric indexing occurs. Raw image bytes are not stored in the database.

MODEL LICENSE NOTE:
    InsightFace pre-trained model weights are for non-commercial research use only.
    Operators are responsible for applicable privacy law, consent requirements,
    and platform terms of service.
"""

from __future__ import annotations

import asyncio
import uuid as _uuid
import warnings
from datetime import UTC, datetime, timedelta
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from backend.api.dependencies import get_repository
from backend.core.config import get_settings
from backend.db.models import (
    FaceInstance,
    ImageArtifact,
    ImageEmbedding,
)
from backend.db.repositories import PostgresInvestigationRepository
from backend.faces import engine as face_engine
from backend.faces.fetcher import fetch_avatar
from backend.faces.pipeline import (
    ImageValidationError,
    MultipleDetectedFaces,
    NoFaceDetected,
    process_avatar_bytes,
    process_reference_image,
)
from backend.faces.similarity import (
    FaceComparison,
    SimilarityResult,
    compare,
    compare_fingerprints,
    similarity_to_evidence,
)
from backend.core.enums import ImageEmbeddingType

router = APIRouter(prefix="/api/searches", tags=["faces"])
Repository = Annotated[PostgresInvestigationRepository, Depends(get_repository)]

_FACE_LIMITATIONS = [
    "Facial similarity is supporting evidence only; it does not independently establish identity.",
    "Similarity thresholds are uncalibrated application heuristics, not scientifically validated probabilities.",
    "Faces may appear dissimilar due to age, pose, lighting, occlusion, compression, or image quality.",
    "Pre-trained model weights are for non-commercial research use. Operators are responsible for applicable law.",
    "Only public profile avatars collected in this investigation are compared. No internet-wide crawling occurs.",
    "This system does not bypass access controls, obtain private photos, or contact any individuals.",
]

# Concurrency guard — prevent hammering face inference with many uploads at once
_active_face_jobs: set[_uuid.UUID] = set()
_face_semaphore_cache: dict[int, asyncio.Semaphore] = {}


def _get_semaphore() -> asyncio.Semaphore:
    concurrency = get_settings().face_inference_concurrency
    if concurrency not in _face_semaphore_cache:
        _face_semaphore_cache[concurrency] = asyncio.Semaphore(concurrency)
    return _face_semaphore_cache[concurrency]


# --------------------------------------------------------------------------- #
# POST /api/searches/{search_id}/reference-image
# --------------------------------------------------------------------------- #
@router.post("/{search_id}/reference-image")
async def upload_reference_image(
    search_id: _uuid.UUID,
    request: Request,
    repository: Repository,
    face_index: int = 0,
):
    """Upload a reference image for face comparison.

    Send raw JPEG/PNG/WebP bytes as the request body, or multipart with
    a 'file' field. Max 8 MB.

    If multiple faces are detected and face_index is not specified (default 0),
    returns a 300 response listing all detected faces for user selection.
    Set ?face_index=N on re-upload to select a specific face.
    """
    settings = get_settings()

    if not settings.face_matching_enabled:
        raise HTTPException(503, "Face matching is disabled on this server.")

    if await repository.get_search(search_id) is None:
        raise HTTPException(404, "Search not found.")

    if search_id in _active_face_jobs:
        raise HTTPException(429, "A face comparison is already running for this search.")

    if not face_engine.is_available():
        raise HTTPException(503, "Face model (insightface/onnxruntime) is not installed.")

    # Read body
    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    data = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(data) + len(chunk) > settings.max_face_upload_bytes:
                    raise HTTPException(413, "Image exceeds upload limit.")
                data.extend(chunk)
    except TimeoutError as exc:
        raise HTTPException(408, "Upload timed out.") from exc

    # Handle multipart form (file field) vs raw bytes
    if content_type == "multipart/form-data":
        # Re-parse: extract 'file' field manually from boundary-encoded body
        # Simpler: instruct client to send raw body. Return helpful error if multipart.
        raise HTTPException(
            422,
            "Send raw image bytes as the request body with Content-Type: image/jpeg, "
            "image/png, or image/webp. Do not use multipart/form-data.",
        )

    _active_face_jobs.add(search_id)
    try:
        async with _get_semaphore():
            return await _process_and_compare(
                search_id=search_id,
                data=bytes(data),
                repository=repository,
                face_index=face_index,
                settings=settings,
            )
    finally:
        _active_face_jobs.discard(search_id)
        data.clear()


async def _process_and_compare(
    *,
    search_id: _uuid.UUID,
    data: bytes,
    repository: PostgresInvestigationRepository,
    face_index: int,
    settings,
) -> JSONResponse:
    """Core logic: validate → embed reference → compare candidates."""

    # 1. Process reference image
    try:
        processed, exif = await process_reference_image(data, face_index=face_index)
    except ImageValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except NoFaceDetected as exc:
        raise HTTPException(422, {"detail": str(exc), "face_status": "NO_FACE"}) from exc
    except MultipleDetectedFaces as exc:
        # Return all faces for user selection — not an error, just needs input
        return JSONResponse(
            status_code=300,
            content={
                "face_status": "MULTIPLE_FACES",
                "message": (
                    f"{len(exc.faces)} faces detected. "
                    "Re-upload with ?face_index=N to select one."
                ),
                "faces": [
                    {
                        "face_index": f.face_index,
                        "detection_confidence": round(f.detection_confidence, 4),
                        "quality_score": round(f.quality_score, 4),
                        "bbox": {
                            "x1": round(f.bbox[0], 1),
                            "y1": round(f.bbox[1], 1),
                            "x2": round(f.bbox[2], 1),
                            "y2": round(f.bbox[3], 1),
                        },
                    }
                    for f in exc.faces
                ],
                "limitations": _FACE_LIMITATIONS,
            },
        )

    fp = processed.image_fingerprint

    # 2. Persist ImageArtifact (reference role)
    retention_expires = datetime.now(UTC) + timedelta(hours=settings.reference_image_retention_hours)
    artifact = ImageArtifact(
        search_run_id=search_id,
        artifact_role="REFERENCE",
        sha256=fp.sha256,
        perceptual_hash=fp.phash,  # legacy field kept for compat
        phash=fp.phash,
        dhash=fp.dhash,
        colorhash=fp.colorhash,
        whash=fp.whash,
        crop_resistant_hash=fp.crop_resistant_hash,
        width=fp.width,
        height=fp.height,
        face_count=processed.face_count,
        face_status="SINGLE_FACE" if processed.face_count == 1 else "MULTIPLE_FACES",
        retention_expires_at=retention_expires,
        exif_metadata=exif,
        quality_score=processed.quality_score,
    )
    repository.session.add(artifact)
    await repository.session.flush()

    # 3. Persist FaceInstance
    fi = FaceInstance(
        image_artifact_id=artifact.id,
        face_index=processed.face_index,
        bounding_box={
            "x1": processed.bbox[0], "y1": processed.bbox[1],
            "x2": processed.bbox[2], "y2": processed.bbox[3],
        },
        detection_confidence=processed.detection_confidence,
        quality_score=processed.quality_score,
        selected_for_reference=True,
    )
    repository.session.add(fi)
    await repository.session.flush()

    # 4. Persist face embedding
    embedding_record = ImageEmbedding(
        image_artifact_id=artifact.id,
        embedding_type=ImageEmbeddingType.FACE,
        model_name=face_engine.MODEL_NAME,
        model_version=face_engine.MODEL_VERSION,
        embedding=processed.embedding.tolist(),
        quality_score=processed.quality_score,
    )
    repository.session.add(embedding_record)
    await repository.session.flush()

    # 5. Compare against discovered candidate profile avatars
    profiles = await repository.list_profile_snapshots_for_search(search_id)
    await repository.session.rollback()  # Detach for read-only iteration

    matches = await _compare_candidates(
        reference_artifact_id=str(artifact.id),
        ref_embedding=processed.embedding,
        ref_quality=processed.quality_score,
        ref_fingerprint={
            "sha256": fp.sha256,
            "pixels_sha256": fp.pixels_sha256,
            "phash": fp.phash,
            "dhash": fp.dhash,
            "colorhash": fp.colorhash,
            "whash": fp.whash,
        },
        profiles=profiles,
        settings=settings,
    )

    return JSONResponse(
        {
            "reference_artifact_id": str(artifact.id),
            "face_status": artifact.face_status,
            "reference_quality": round(processed.quality_score, 4),
            "face_index_used": processed.face_index,
            "multiple_faces_in_image": processed.multiple_faces_in_image,
            "exif_summary": _safe_exif_summary(exif),
            "matches": matches,
            "checked": len([m for m in matches if m["status"] != "NO_PUBLIC_IMAGE"]),
            "model": face_engine.MODEL_NAME,
            "model_version": face_engine.MODEL_VERSION,
            "metric": face_engine.METRIC,
            "calibrated": False,
            "identity_scores_changed": False,
            "model_license": face_engine.LICENSE_NOTE,
            "limitations": _FACE_LIMITATIONS,
        },
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def _compare_candidates(
    *,
    reference_artifact_id: str,
    ref_embedding: np.ndarray,
    ref_quality: float,
    ref_fingerprint: dict,
    profiles,
    settings,
) -> list[dict]:
    """Fetch, embed, and compare all candidate profile avatars."""
    semaphore = asyncio.Semaphore(settings.face_inference_concurrency)
    results = []

    async def _process_one(profile) -> dict:
        base = {
            "profile_id": str(profile.id),
            "platform": profile.platform,
            "username": profile.username,
            "profile_url": profile.canonical_url,
            "avatar_url": profile.avatar_url,
        }
        if not profile.avatar_url:
            return {**base, "status": "NO_PUBLIC_IMAGE", "message": "No public avatar collected."}

        async with semaphore:
            try:
                async with asyncio.timeout(20):
                    avatar_data = await fetch_avatar(profile.avatar_url)
            except Exception as exc:
                return {**base, "status": "FETCH_FAILED", "message": str(exc)[:120]}

            result = await process_avatar_bytes(avatar_data)

        if result.status != "PROCESSED" or result.face is None:
            return {**base, "status": result.status, "message": result.message}

        # Fingerprint comparison first (fast path before face cosine)
        fp_cmp = {}
        if result.fingerprint:
            cand_fp = {
                "sha256": result.fingerprint.sha256,
                "pixels_sha256": result.fingerprint.pixels_sha256,
                "phash": result.fingerprint.phash,
                "dhash": result.fingerprint.dhash,
                "colorhash": result.fingerprint.colorhash,
                "whash": result.fingerprint.whash,
            }
            fp_cmp = compare_fingerprints(ref_fingerprint, cand_fp)

        # If exact file or pixel match — skip expensive face comparison
        if fp_cmp.get("exact_file") or fp_cmp.get("same_pixels"):
            return {
                **base,
                "status": "EXACT_IMAGE",
                "classification": "STRONG_SUPPORT",
                "similarity": 1.0,
                "quality": round(result.face.quality_score, 4),
                "calibrated": False,
                "fingerprint_match": fp_cmp,
                "message": "Exact same image file detected.",
                "multiple_faces_in_avatar": result.face.multiple_faces_in_image,
            }

        sim_result: SimilarityResult = compare(
            ref_embedding,
            result.face.embedding,
            reference_quality=ref_quality,
            candidate_quality=result.face.quality_score,
        )

        classification = sim_result.classification
        similarity_val = round(sim_result.cosine_similarity, 6)

        display_status = _classification_to_status(classification)

        return {
            **base,
            "status": display_status,
            "classification": classification,
            "similarity": similarity_val,
            "quality": round(result.face.quality_score, 4),
            "calibrated": False,
            "fingerprint_match": fp_cmp if fp_cmp else None,
            "multiple_faces_in_avatar": result.face.multiple_faces_in_image,
            "message": _classification_message(classification, similarity_val),
        }

    tasks = [_process_one(p) for p in profiles]
    raw = await asyncio.gather(*tasks)

    # Sort: exact image → strong support → supporting → inconclusive → no image
    order = {
        "EXACT_IMAGE": 0,
        "STRONG_SUPPORT": 1,
        "SUPPORTING": 2,
        "INCONCLUSIVE": 3,
        "POSSIBLE_MISMATCH": 4,
        "NO_COMPARISON": 5,
        "LOW_QUALITY": 6,
        "NO_FACE": 7,
        "FETCH_FAILED": 8,
        "NO_PUBLIC_IMAGE": 9,
    }
    return sorted(raw, key=lambda r: order.get(r.get("status", ""), 99))


def _classification_to_status(cls: str) -> str:
    return {
        FaceComparison.STRONG_SUPPORT: "STRONG_SUPPORT",
        FaceComparison.SUPPORTING: "SUPPORTING",
        FaceComparison.INCONCLUSIVE: "INCONCLUSIVE",
        FaceComparison.POSSIBLE_MISMATCH: "POSSIBLE_MISMATCH",
        FaceComparison.NO_COMPARISON: "NO_COMPARISON",
    }.get(cls, "INCONCLUSIVE")


def _classification_message(cls: str, sim: float) -> str:
    return {
        FaceComparison.STRONG_SUPPORT: (
            "The supplied reference face is strongly similar to this candidate's public avatar. "
            "This is supporting evidence — not a confirmed identity."
        ),
        FaceComparison.SUPPORTING: (
            "Moderate visual similarity between the reference and this candidate's avatar. "
            "Supporting evidence only."
        ),
        FaceComparison.INCONCLUSIVE: "Visual similarity is inconclusive under the current model and thresholds.",
        FaceComparison.POSSIBLE_MISMATCH: (
            "Low visual similarity. Weak contradicting evidence. "
            "Image quality, age, pose, or lighting may cause false negatives."
        ),
        FaceComparison.NO_COMPARISON: "Image quality was too low for a reliable comparison.",
    }.get(cls, "No comparison performed.")


def _safe_exif_summary(exif: dict) -> dict:
    """Return OSINT-relevant EXIF fields only. Omit large binary fields."""
    if not exif:
        return {}
    keep = {
        "Make", "Model", "Software", "DateTime", "DateTimeOriginal",
        "DateTimeDigitized", "LensModel", "Artist", "Copyright",
        "ImageDescription", "gps_decimal", "_source",
        # ExifTool namespaced versions
        "EXIF:Make", "EXIF:Model", "EXIF:Software",
        "EXIF:DateTimeOriginal", "Composite:GPSLatitude",
        "Composite:GPSLongitude", "Composite:GPSPosition",
    }
    return {k: v for k, v in exif.items() if k in keep}


# --------------------------------------------------------------------------- #
# GET /api/searches/{search_id}/face-matches
# --------------------------------------------------------------------------- #
@router.get("/{search_id}/face-matches")
async def get_face_matches(search_id: _uuid.UUID, repository: Repository):
    """Return stored face embedding artifacts for this search."""
    if await repository.get_search(search_id) is None:
        raise HTTPException(404, "Search not found.")

    from sqlalchemy import select

    artifacts = (
        await repository.session.scalars(
            select(ImageArtifact)
            .where(
                ImageArtifact.search_run_id == search_id,
                ImageArtifact.artifact_role == "REFERENCE",
            )
            .order_by(ImageArtifact.observed_at.desc())
            .limit(5)
        )
    ).all()

    if not artifacts:
        return JSONResponse(
            {
                "reference_artifacts": [],
                "message": "No reference image has been uploaded for this search yet.",
                "limitations": _FACE_LIMITATIONS,
            }
        )

    result = []
    for art in artifacts:
        result.append(
            {
                "artifact_id": str(art.id),
                "face_status": art.face_status,
                "face_count": art.face_count,
                "quality_score": art.quality_score,
                "uploaded_at": art.observed_at.isoformat(),
                "retention_expires_at": (
                    art.retention_expires_at.isoformat() if art.retention_expires_at else None
                ),
                "exif_summary": _safe_exif_summary(art.exif_metadata or {}),
                "model": face_engine.MODEL_NAME,
                "model_version": face_engine.MODEL_VERSION,
                "metric": face_engine.METRIC,
                "model_license": face_engine.LICENSE_NOTE,
            }
        )

    return JSONResponse(
        {
            "reference_artifacts": result,
            "limitations": _FACE_LIMITATIONS,
        },
        headers={"Cache-Control": "no-store"},
    )
