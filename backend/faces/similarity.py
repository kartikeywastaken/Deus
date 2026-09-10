"""Face similarity calculation and evidence generation.

Computes cosine similarity between L2-normalised 512-D ArcFace embeddings and
maps raw scores to EvidenceSignal objects for the correlation engine.

Thresholds are UNCALIBRATED application heuristics.
They have NOT been evaluated against a labelled dataset.
All API responses include "calibrated": false.

Threshold calibration requires:
  1. A set of authorised ground-truth image pairs (same/different person).
  2. ROC analysis to choose operating points appropriate to the use case.
Do not treat these numbers as scientifically validated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.faces.engine import EMBEDDING_DIM, METRIC, MODEL_NAME, MODEL_VERSION

# --------------------------------------------------------------------------- #
# Uncalibrated thresholds — explicitly labelled in all outputs
# --------------------------------------------------------------------------- #
# These are starting points only. Adjust after evaluating against authorised data.
STRONG_SUPPORT_THRESHOLD: float = 0.82   # UNCALIBRATED
SUPPORT_THRESHOLD: float = 0.68          # UNCALIBRATED
REVIEW_THRESHOLD: float = 0.55           # UNCALIBRATED
CONTRADICTION_THRESHOLD: float = 0.28    # UNCALIBRATED — only fires if both quality > 0.60


class FaceComparison(str):
    """Similarity classification strings."""
    STRONG_SUPPORT = "STRONG_SUPPORT"
    SUPPORTING = "SUPPORTING"
    INCONCLUSIVE = "INCONCLUSIVE"
    POSSIBLE_MISMATCH = "POSSIBLE_MISMATCH"
    NO_COMPARISON = "NO_COMPARISON"


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two L2-normalised unit vectors.

    Since both are L2-normalised by ArcFace, this is just the dot product.
    Result is in [-1, 1]; higher = more similar.
    """
    if a.shape != (EMBEDDING_DIM,) or b.shape != (EMBEDDING_DIM,):
        raise ValueError(f"Expected shape ({EMBEDDING_DIM},); got {a.shape} and {b.shape}.")
    # Clip to [-1, 1] to guard against floating-point noise
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


@dataclass(slots=True)
class SimilarityResult:
    """Raw similarity + classification for one reference–candidate pair."""

    cosine_similarity: float
    classification: str           # FaceComparison value
    calibrated: bool = False      # Always False until formally calibrated
    reference_quality: float = 0.0
    candidate_quality: float = 0.0
    model: str = MODEL_NAME
    model_version: str = MODEL_VERSION
    metric: str = METRIC

    def as_dict(self) -> dict[str, Any]:
        return {
            "cosine_similarity": round(self.cosine_similarity, 6),
            "classification": self.classification,
            "calibrated": self.calibrated,
            "reference_quality": round(self.reference_quality, 4),
            "candidate_quality": round(self.candidate_quality, 4),
            "model": self.model,
            "model_version": self.model_version,
            "metric": self.metric,
            "threshold_note": (
                "Thresholds are uncalibrated application heuristics. "
                "Do not treat them as scientifically validated probabilities."
            ),
        }


def compare(
    reference_embedding: np.ndarray,
    candidate_embedding: np.ndarray,
    *,
    reference_quality: float = 1.0,
    candidate_quality: float = 1.0,
) -> SimilarityResult:
    """Compare two face embeddings and return a structured result.

    Low-quality images are not compared; they return INCONCLUSIVE.
    """
    if reference_quality < 0.3 or candidate_quality < 0.3:
        return SimilarityResult(
            cosine_similarity=0.0,
            classification=FaceComparison.NO_COMPARISON,
            reference_quality=reference_quality,
            candidate_quality=candidate_quality,
        )

    sim = cosine_similarity(reference_embedding, candidate_embedding)

    if sim >= STRONG_SUPPORT_THRESHOLD:
        cls = FaceComparison.STRONG_SUPPORT
    elif sim >= SUPPORT_THRESHOLD:
        cls = FaceComparison.SUPPORTING
    elif sim <= CONTRADICTION_THRESHOLD and reference_quality > 0.60 and candidate_quality > 0.60:
        cls = FaceComparison.POSSIBLE_MISMATCH
    elif sim < REVIEW_THRESHOLD:
        cls = FaceComparison.INCONCLUSIVE
    else:
        cls = FaceComparison.INCONCLUSIVE

    return SimilarityResult(
        cosine_similarity=sim,
        classification=cls,
        reference_quality=reference_quality,
        candidate_quality=candidate_quality,
    )


# --------------------------------------------------------------------------- #
# Evidence signal production (feeds correlation engine)
# --------------------------------------------------------------------------- #
def similarity_to_evidence(
    result: SimilarityResult,
    *,
    reference_profile_id: str | None,
    candidate_profile_id: str,
    reference_artifact_id: str,
    candidate_artifact_id: str,
    candidate_source_url: str | None,
) -> dict[str, Any] | None:
    """Convert a SimilarityResult into an evidence signal dict.

    Returns None for cases that should not produce evidence
    (NO_COMPARISON, INCONCLUSIVE).

    The dict structure matches what extract_image_evidence() and the
    correlation engine expect.
    """
    sim = result.cosine_similarity
    cls = result.classification

    if cls == FaceComparison.NO_COMPARISON:
        return None

    if cls == FaceComparison.STRONG_SUPPORT:
        direction = "SUPPORT"
        normalized_score = min(1.0, (sim - SUPPORT_THRESHOLD) / (1.0 - SUPPORT_THRESHOLD))
        reliability = min(0.90, 0.70 + result.reference_quality * 0.1 + result.candidate_quality * 0.1)
        explanation = (
            "The supplied reference face is strongly similar to the public avatar "
            "associated with this candidate. This is supporting evidence and should be "
            "interpreted alongside username, domain, and profile-link evidence."
        )
    elif cls == FaceComparison.SUPPORTING:
        direction = "SUPPORT"
        normalized_score = (sim - REVIEW_THRESHOLD) / (STRONG_SUPPORT_THRESHOLD - REVIEW_THRESHOLD)
        reliability = min(0.75, 0.55 + result.reference_quality * 0.1 + result.candidate_quality * 0.1)
        explanation = (
            "A bounded face comparison found moderate visual similarity between the "
            "reference image and this candidate's public avatar. "
            "This is supporting evidence only."
        )
    elif cls == FaceComparison.POSSIBLE_MISMATCH:
        # Conservative: only generate negative evidence when both images are high quality.
        direction = "CONTRADICT"
        normalized_score = 1.0 - sim  # Higher contradiction when similarity is lower
        reliability = 0.55  # Still conservative — faces can differ due to age/angle
        explanation = (
            "A bounded face comparison found low visual similarity between the "
            "reference image and this candidate's public avatar. "
            "This is weak contradicting evidence. "
            "Factors such as image quality, age, pose, or lighting can cause "
            "false negatives. Do not treat this as definitive."
        )
    else:
        return None  # INCONCLUSIVE — no evidence generated

    return {
        "signal_type": "FACE_SIMILARITY" if direction == "SUPPORT" else "DIFFERENT_FACE",
        "direction": direction,
        "normalized_score": round(normalized_score, 6),
        "reliability": round(reliability, 4),
        "evidence_family": "IMAGE_IDENTITY",
        "raw_value": {
            **result.as_dict(),
        },
        "explanation": explanation,
        "provenance": {
            "reference_profile_id": reference_profile_id,
            "candidate_profile_id": candidate_profile_id,
            "reference_artifact_id": reference_artifact_id,
            "candidate_artifact_id": candidate_artifact_id,
            "candidate_source_url": candidate_source_url,
            "model": result.model,
            "model_version": result.model_version,
            "metric": result.metric,
        },
    }


# --------------------------------------------------------------------------- #
# Image fingerprint comparison (before face inference — fast path)
# --------------------------------------------------------------------------- #
def compare_fingerprints(ref_fp: dict[str, Any], cand_fp: dict[str, Any]) -> dict[str, Any]:
    """Compare image fingerprints using all available hash algorithms.

    Returns a dict with:
      exact_file:        bool — same raw bytes
      same_pixels:       bool — same decoded pixels
      phash_distance:    int  — hamming distance (lower = more similar)
      dhash_distance:    int
      colorhash_distance: int (5-bit buckets, scale differs from phash)
      whash_distance:    int
      near_copy:         bool — conservative multi-hash near-duplicate signal
    """
    if not ref_fp or not cand_fp:
        return {"error": "Missing fingerprint"}

    def ham(h1: str, h2: str) -> int:
        try:
            return (int(h1, 16) ^ int(h2, 16)).bit_count()
        except (ValueError, TypeError):
            return 999

    exact_file = ref_fp.get("sha256") == cand_fp.get("sha256")
    same_pixels = (
        ref_fp.get("pixels_sha256") == cand_fp.get("pixels_sha256")
        and not exact_file  # Avoid double-reporting
    )

    ph = ham(ref_fp.get("phash", ""), cand_fp.get("phash", ""))
    dh = ham(ref_fp.get("dhash", ""), cand_fp.get("dhash", ""))
    ch = ham(ref_fp.get("colorhash", ""), cand_fp.get("colorhash", ""))
    wh = ham(ref_fp.get("whash", ""), cand_fp.get("whash", ""))

    # Conservative near-copy: requires multiple algorithms to agree
    near_copy = (not exact_file and not same_pixels and ph <= 6 and dh <= 6 and wh <= 8)

    return {
        "exact_file": exact_file,
        "same_pixels": same_pixels,
        "phash_distance": ph,
        "dhash_distance": dh,
        "colorhash_distance": ch,
        "whash_distance": wh,
        "near_copy": near_copy,
    }
