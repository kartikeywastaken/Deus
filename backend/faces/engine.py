"""InsightFace engine wrapper — lazy-loads on first use, thread-safe.

Model pack: buffalo_sc  (RetinaFace detector + ArcFace ResNet-50 recognition)
Embedding dimension: 512  (float32, L2-normalised by ArcFace head)
Distance metric: cosine similarity (dot product of unit vectors)

The engine is loaded once per process. Face inference is CPU-bound; run it in
asyncio.to_thread() to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

_lock = threading.Lock()
_engine: "_FaceEngine | None" = None

MODEL_NAME = "buffalo_sc"
MODEL_VERSION = "1.0"
EMBEDDING_DIM = 512
METRIC = "cosine"
LICENSE_NOTE = (
    "InsightFace code: MIT. Pre-trained weights: non-commercial research only. "
    "Operators are responsible for applicable privacy law and platform terms."
)

# Quality thresholds — uncalibrated application heuristics.
# A face is considered acceptable for comparison only if det_score >= MIN_DETECT_SCORE
# AND the face area is >= MIN_FACE_AREA_FRACTION of the image.
MIN_DETECT_SCORE: float = 0.65
MIN_FACE_AREA_FRACTION: float = 0.005  # face bbox must be ≥ 0.5 % of image pixels


@dataclass(slots=True)
class DetectedFace:
    """One face extracted from an image."""

    face_index: int
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    detection_confidence: float
    quality_score: float  # application heuristic, NOT a calibrated probability
    embedding: np.ndarray  # shape (512,), L2-normalized
    face_area_fraction: float


class FaceEngineError(RuntimeError):
    """Raised when the engine cannot be loaded."""


class _FaceEngine:
    def __init__(self) -> None:
        import insightface
        from insightface.app import FaceAnalysis

        self._app = FaceAnalysis(
            name=MODEL_NAME,
            providers=["CPUExecutionProvider"],
        )
        # det_size controls the internal detection resolution; 320x320 is fast on CPU.
        self._app.prepare(ctx_id=-1, det_size=(320, 320))
        self._insightface_version = insightface.__version__
        import onnxruntime as ort

        self._ort_version = ort.__version__
        self._runtime_providers = ort.get_available_providers()

    def analyse(self, rgb_array: np.ndarray) -> list[DetectedFace]:
        """Return all detected faces in descending detection-score order."""
        h, w = rgb_array.shape[:2]
        image_pixels = h * w
        faces = self._app.get(rgb_array)
        results: list[DetectedFace] = []
        for idx, face in enumerate(faces):
            det_score = float(getattr(face, "det_score", 0.0))
            bbox = tuple(float(v) for v in face.bbox)  # type: ignore[assignment]
            x1, y1, x2, y2 = bbox
            face_area = max(0.0, (x2 - x1) * (y2 - y1))
            area_fraction = face_area / image_pixels if image_pixels > 0 else 0.0
            quality = _quality_score(det_score, area_fraction, rgb_array, bbox)
            # Embedding from ArcFace head — already L2-normalised.
            raw_emb = np.array(face.embedding, dtype=np.float32)
            norm = np.linalg.norm(raw_emb)
            embedding = raw_emb / norm if norm > 1e-9 else raw_emb
            results.append(
                DetectedFace(
                    face_index=idx,
                    bbox=bbox,
                    detection_confidence=det_score,
                    quality_score=quality,
                    embedding=embedding,
                    face_area_fraction=area_fraction,
                )
            )
        results.sort(key=lambda f: f.detection_confidence, reverse=True)
        return results

    def healthcheck_info(self) -> dict[str, Any]:
        return {
            "status": "AVAILABLE",
            "model": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "insightface_version": self._insightface_version,
            "onnxruntime_version": self._ort_version,
            "available_providers": self._runtime_providers,
            "embedding_dim": EMBEDDING_DIM,
            "metric": METRIC,
            "model_license": LICENSE_NOTE,
        }


def _quality_score(
    det_score: float,
    area_fraction: float,
    rgb: np.ndarray,
    bbox: tuple[float, float, float, float],
) -> float:
    """Return a bounded quality score in [0, 1].

    This is a coarse application heuristic combining:
    - detection confidence (primary signal)
    - face size relative to image (too small = poor quality)
    - image brightness in the face crop (near-black or blown-out = unreliable)

    It is NOT a calibrated biometric quality metric.
    """
    if det_score < MIN_DETECT_SCORE:
        return 0.0
    size_score = min(1.0, area_fraction / 0.05)  # normalise: 5 % image area = score 1.0
    x1, y1, x2, y2 = (int(max(0, v)) for v in bbox)
    crop = rgb[y1:y2, x1:x2]
    if crop.size == 0:
        brightness_score = 0.5
    else:
        mean_brightness = float(crop.mean()) / 255.0
        # Penalise near-black (< 5 %) and blown-out (> 95 %)
        brightness_score = 1.0 - abs(mean_brightness - 0.5) * 2
        brightness_score = max(0.0, brightness_score)
    return round(0.6 * det_score + 0.25 * size_score + 0.15 * brightness_score, 4)


def _load_engine() -> _FaceEngine:
    """Load the InsightFace engine, raising FaceEngineError on failure."""
    try:
        return _FaceEngine()
    except Exception as exc:
        raise FaceEngineError(f"InsightFace engine failed to load: {exc}") from exc


def get_engine() -> _FaceEngine:
    """Return the process-wide engine instance, loading it on first call."""
    global _engine
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is None:
            _engine = _load_engine()
    return _engine


async def get_engine_async() -> _FaceEngine:
    """Async-safe engine accessor — loads in a thread on first call."""
    global _engine
    if _engine is not None:
        return _engine
    engine = await asyncio.to_thread(_load_engine)
    with _lock:
        if _engine is None:
            _engine = engine
    return _engine


def is_available() -> bool:
    """Return True if the engine can be imported (no model download check)."""
    try:
        import insightface  # noqa: F401
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


async def healthcheck() -> dict[str, Any]:
    """Return a dict suitable for the doctor endpoint."""
    if not is_available():
        return {
            "status": "UNAVAILABLE",
            "reason": "insightface or onnxruntime not installed",
            "model": MODEL_NAME,
            "embedding_dim": EMBEDDING_DIM,
            "metric": METRIC,
            "model_license": LICENSE_NOTE,
        }
    try:
        engine = await get_engine_async()
        info = engine.healthcheck_info()
        # Quick self-check: embed a tiny synthetic image (no real face — just verifies inference path).
        import numpy as np

        dummy = np.zeros((112, 112, 3), dtype=np.uint8)
        # We don't assert a face is detected — just that the call doesn't crash.
        await asyncio.to_thread(engine.analyse, dummy)
        info["self_check"] = "PASSED"
        return info
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "reason": str(exc),
            "model": MODEL_NAME,
            "embedding_dim": EMBEDDING_DIM,
            "metric": METRIC,
        }
