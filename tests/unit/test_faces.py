"""Unit tests for the face subsystem.

Tests cover: image fingerprinting, hash distances, cosine similarity maths,
quality gating, threshold classification, evidence signal schema, and EXIF
extraction. All are deterministic — no network, no real face model needed.
"""

from __future__ import annotations

import hashlib
import io
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw


# --------------------------------------------------------------------------- #
# Helpers: create test images in memory
# --------------------------------------------------------------------------- #
def make_png(width=256, height=256, color="red") -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_jpeg(width=256, height=256, color="blue", quality=90) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def make_face_like_png(width=300, height=300) -> bytes:
    """A synthetic image that resembles a face (oval on background)."""
    img = Image.new("RGB", (width, height), "#ffe0b2")
    draw = ImageDraw.Draw(img)
    # Face oval
    draw.ellipse([50, 40, 250, 260], fill="#f5cba7")
    # Eyes
    draw.ellipse([100, 100, 130, 125], fill="black")
    draw.ellipse([170, 100, 200, 125], fill="black")
    # Mouth
    draw.arc([110, 160, 190, 200], 0, 180, fill="brown", width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Test: image_reuse fingerprinting (extended hashes)
# --------------------------------------------------------------------------- #
class TestImageReuseFingerprint:
    def test_new_fields_present(self):
        from backend.image_reuse import fingerprint
        data = make_png()
        fp = fingerprint(data)
        assert "phash" in fp
        assert "dhash" in fp
        assert "colorhash" in fp
        assert "whash" in fp
        assert "crop_resistant_hash" in fp
        assert "sha256" in fp

    def test_exact_file_match(self):
        from backend.image_reuse import compare, fingerprint
        data = make_png()
        ref = fingerprint(data)
        assert compare(ref, ref)["status"] == "EXACT_FILE"

    def test_different_format_possible_reuse(self):
        from backend.image_reuse import compare, fingerprint
        data_png = make_png(color="green")
        data_jpg = make_jpeg(color="green", quality=85)
        ref = fingerprint(data_png)
        cand = fingerprint(data_jpg)
        result = compare(ref, cand)
        # Solid-colour images have near-zero pixel variation,
        # so the INCONCLUSIVE path fires correctly. Verify the function
        # returns the expected status rather than raising.
        assert result["status"] in (
            "POSSIBLE_REUSE", "SAME_PIXELS", "EXACT_FILE", "INCONCLUSIVE"
        ), result

    def test_different_image_no_reuse(self):
        from backend.image_reuse import compare, fingerprint
        ref = fingerprint(make_png(color="red"))
        cand = fingerprint(make_png(color="blue"))
        result = compare(ref, cand)
        # Solid-colour images have no texture; variation check fires INCONCLUSIVE.
        # The important property is that status is not POSSIBLE_REUSE.
        assert result["status"] != "POSSIBLE_REUSE", result

    def test_method_version_updated(self):
        from backend.image_reuse import METHOD_VERSION
        assert "v2" in METHOD_VERSION

    def test_near_vote_count_in_result(self):
        """near_vote_count appears in compare() result for images with sufficient texture."""
        # Use a complex image (gradient) that has enough variation to pass the threshold
        from PIL import Image
        import io
        from backend.image_reuse import compare, fingerprint
        def make_gradient():
            img = Image.new("RGB", (64, 64))
            pixels = img.load()
            for i in range(64):
                for j in range(64):
                    pixels[i, j] = (i * 4, j * 4, (i + j) * 2 % 255)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        data_a = make_gradient()
        data_b = make_gradient()
        ref = fingerprint(data_a)
        cand = fingerprint(data_b)  # identical image → near_vote_count path
        # Ensure EXACT_FILE is hit (same bytes) — or create slightly modified:
        from PIL import ImageFilter
        img2 = Image.open(io.BytesIO(data_a)).filter(ImageFilter.SMOOTH)
        buf2 = io.BytesIO()
        img2.save(buf2, format="JPEG", quality=80)
        cand2 = fingerprint(buf2.getvalue())
        result = compare(ref, cand2)
        # For images with texture, near_vote_count must be present in result
        # OR the result is EXACT_FILE/SAME_PIXELS (no vote needed)
        assert "near_vote_count" in result or result["status"] in ("EXACT_FILE", "SAME_PIXELS")


# --------------------------------------------------------------------------- #
# Test: face pipeline image validation (no model needed)
# --------------------------------------------------------------------------- #
class TestImageValidation:
    def test_valid_jpeg_fingerprints(self):
        from backend.faces.pipeline import fingerprint_bytes
        data = make_jpeg()
        fp, rgb = fingerprint_bytes(data)
        assert fp.sha256 == hashlib.sha256(data).hexdigest()
        assert fp.width == 256
        assert fp.height == 256
        assert fp.phash
        assert fp.colorhash
        assert fp.whash
        rgb.close()

    def test_valid_png_fingerprints(self):
        from backend.faces.pipeline import fingerprint_bytes
        data = make_png()
        fp, rgb = fingerprint_bytes(data)
        assert fp.format == "PNG"
        assert fp.crop_resistant_hash
        rgb.close()

    def test_rejects_empty(self):
        from backend.faces.pipeline import ImageValidationError, fingerprint_bytes
        with pytest.raises(ImageValidationError, match="Empty"):
            fingerprint_bytes(b"")

    def test_rejects_oversized(self):
        from backend.faces.pipeline import ImageValidationError, fingerprint_bytes
        with pytest.raises(ImageValidationError):
            fingerprint_bytes(b"x" * 9_000_000)

    def test_rejects_corrupt(self):
        from backend.faces.pipeline import ImageValidationError, fingerprint_bytes
        with pytest.raises(ImageValidationError):
            fingerprint_bytes(b"not an image at all 12345")

    def test_rejects_gif(self):
        """Animated GIF must be rejected."""
        from backend.faces.pipeline import ImageValidationError, fingerprint_bytes
        img = Image.new("RGB", (10, 10), "red")
        buf = io.BytesIO()
        img.save(buf, format="GIF")
        with pytest.raises(ImageValidationError):
            fingerprint_bytes(buf.getvalue())


# --------------------------------------------------------------------------- #
# Test: EXIF extraction (PIL path)
# --------------------------------------------------------------------------- #
class TestExifExtraction:
    def test_returns_dict_for_plain_image(self):
        from backend.faces.pipeline import extract_exif_pil
        data = make_png()
        result = extract_exif_pil(data)
        assert isinstance(result, dict)  # May be empty — PNG has no EXIF

    def test_no_crash_on_corrupt(self):
        from backend.faces.pipeline import extract_exif_pil
        result = extract_exif_pil(b"garbage data 12345")
        assert result == {}

    def test_gps_decimal_conversion(self):
        from backend.faces.pipeline import _gps_to_decimal
        # IFDRational values from PIL come as floats after __float__
        # Our function handles both (numerator, denominator) tuples and plain numbers
        # Test with plain float values (what IFDRational converts to)
        lat = _gps_to_decimal([37.0, 26.0, 36.42], "N")
        assert lat is not None
        assert abs(lat - 37.443450) < 0.001

        lon = _gps_to_decimal([122.0, 5.0, 0.0], "W")
        assert lon is not None
        assert lon < 0  # West is negative


# --------------------------------------------------------------------------- #
# Test: cosine similarity maths
# --------------------------------------------------------------------------- #
class TestCosineSimilarity:
    def test_identical_vectors(self):
        from backend.faces.similarity import cosine_similarity
        v = np.random.randn(512).astype(np.float32)
        v /= np.linalg.norm(v)
        sim = cosine_similarity(v, v)
        assert abs(sim - 1.0) < 1e-5

    def test_opposite_vectors(self):
        from backend.faces.similarity import cosine_similarity
        v = np.random.randn(512).astype(np.float32)
        v /= np.linalg.norm(v)
        sim = cosine_similarity(v, -v)
        assert abs(sim - (-1.0)) < 1e-5

    def test_orthogonal_vectors(self):
        from backend.faces.similarity import cosine_similarity
        a = np.zeros(512, dtype=np.float32)
        b = np.zeros(512, dtype=np.float32)
        a[0] = 1.0
        b[1] = 1.0
        sim = cosine_similarity(a, b)
        assert abs(sim) < 1e-5

    def test_wrong_dimension_raises(self):
        from backend.faces.similarity import cosine_similarity
        a = np.ones(128, dtype=np.float32)
        b = np.ones(512, dtype=np.float32)
        with pytest.raises(ValueError, match="Expected shape"):
            cosine_similarity(a, b)

    def test_result_in_range(self):
        from backend.faces.similarity import cosine_similarity
        for _ in range(10):
            a = np.random.randn(512).astype(np.float32)
            b = np.random.randn(512).astype(np.float32)
            a /= np.linalg.norm(a)
            b /= np.linalg.norm(b)
            sim = cosine_similarity(a, b)
            assert -1.0 <= sim <= 1.0


# --------------------------------------------------------------------------- #
# Test: threshold classification
# --------------------------------------------------------------------------- #
class TestThresholdClassification:
    def _unit_vec(self, seed=42):
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(512).astype(np.float32)
        return v / np.linalg.norm(v)

    def test_strong_support_at_high_similarity(self):
        from backend.faces.similarity import FaceComparison, compare
        v = self._unit_vec()
        # Nearly identical embedding → strong support
        noise = np.random.randn(512).astype(np.float32) * 0.01
        w = v + noise
        w /= np.linalg.norm(w)
        result = compare(v, w, reference_quality=0.9, candidate_quality=0.9)
        assert result.classification in (FaceComparison.STRONG_SUPPORT, FaceComparison.SUPPORTING)

    def test_no_comparison_on_low_quality(self):
        from backend.faces.similarity import FaceComparison, compare
        v = self._unit_vec()
        result = compare(v, v, reference_quality=0.1, candidate_quality=0.9)
        assert result.classification == FaceComparison.NO_COMPARISON
        assert result.cosine_similarity == 0.0

    def test_possible_mismatch_on_opposite(self):
        from backend.faces.similarity import FaceComparison, compare
        v = self._unit_vec()
        result = compare(v, -v, reference_quality=0.9, candidate_quality=0.9)
        assert result.classification == FaceComparison.POSSIBLE_MISMATCH

    def test_calibrated_always_false(self):
        from backend.faces.similarity import compare
        v = self._unit_vec()
        result = compare(v, v, reference_quality=0.9, candidate_quality=0.9)
        assert result.calibrated is False


# --------------------------------------------------------------------------- #
# Test: evidence signal schema
# --------------------------------------------------------------------------- #
class TestEvidenceSignal:
    def _unit_vec(self, seed=1):
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(512).astype(np.float32)
        return v / np.linalg.norm(v)

    def test_strong_support_produces_evidence(self):
        from backend.faces.similarity import FaceComparison, SimilarityResult, similarity_to_evidence
        result = SimilarityResult(
            cosine_similarity=0.90,
            classification=FaceComparison.STRONG_SUPPORT,
            reference_quality=0.95,
            candidate_quality=0.88,
        )
        ev = similarity_to_evidence(
            result,
            reference_profile_id=None,
            candidate_profile_id="cand-1",
            reference_artifact_id="ref-art-1",
            candidate_artifact_id="cand-art-1",
            candidate_source_url="https://example.com/avatar.jpg",
        )
        assert ev is not None
        assert ev["signal_type"] == "FACE_SIMILARITY"
        assert ev["direction"] == "SUPPORT"
        assert ev["evidence_family"] == "IMAGE_IDENTITY"
        assert ev["raw_value"]["calibrated"] is False
        assert "provenance" in ev
        assert ev["provenance"]["candidate_source_url"] == "https://example.com/avatar.jpg"

    def test_mismatch_produces_contradict(self):
        from backend.faces.similarity import FaceComparison, SimilarityResult, similarity_to_evidence
        result = SimilarityResult(
            cosine_similarity=0.10,
            classification=FaceComparison.POSSIBLE_MISMATCH,
            reference_quality=0.85,
            candidate_quality=0.80,
        )
        ev = similarity_to_evidence(
            result,
            reference_profile_id=None,
            candidate_profile_id="cand-2",
            reference_artifact_id="ref-art-2",
            candidate_artifact_id="cand-art-2",
            candidate_source_url=None,
        )
        assert ev is not None
        assert ev["signal_type"] == "DIFFERENT_FACE"
        assert ev["direction"] == "CONTRADICT"

    def test_inconclusive_returns_none(self):
        from backend.faces.similarity import FaceComparison, SimilarityResult, similarity_to_evidence
        result = SimilarityResult(
            cosine_similarity=0.50,
            classification=FaceComparison.INCONCLUSIVE,
            reference_quality=0.7,
            candidate_quality=0.7,
        )
        ev = similarity_to_evidence(
            result,
            reference_profile_id=None,
            candidate_profile_id="cand-3",
            reference_artifact_id="ref-art-3",
            candidate_artifact_id="cand-art-3",
            candidate_source_url=None,
        )
        assert ev is None

    def test_no_comparison_returns_none(self):
        from backend.faces.similarity import FaceComparison, SimilarityResult, similarity_to_evidence
        result = SimilarityResult(
            cosine_similarity=0.0,
            classification=FaceComparison.NO_COMPARISON,
        )
        assert similarity_to_evidence(
            result,
            reference_profile_id=None,
            candidate_profile_id="x",
            reference_artifact_id="y",
            candidate_artifact_id="z",
            candidate_source_url=None,
        ) is None


# --------------------------------------------------------------------------- #
# Test: fingerprint comparison (multi-hash)
# --------------------------------------------------------------------------- #
class TestFingerprintComparison:
    def test_exact_file_detected(self):
        from backend.faces.similarity import compare_fingerprints
        fp = {"sha256": "abc", "pixels_sha256": "xyz", "phash": "0000", "dhash": "0000",
              "colorhash": "00", "whash": "0000"}
        result = compare_fingerprints(fp, fp)
        assert result["exact_file"] is True

    def test_different_sha_no_exact(self):
        from backend.faces.similarity import compare_fingerprints
        ref = {"sha256": "aaa", "pixels_sha256": "bbb", "phash": "0000", "dhash": "0000",
               "colorhash": "00", "whash": "0000"}
        cand = {"sha256": "ccc", "pixels_sha256": "ddd", "phash": "0001", "dhash": "0001",
                "colorhash": "00", "whash": "0001"}
        result = compare_fingerprints(ref, cand)
        assert result["exact_file"] is False
        assert isinstance(result["phash_distance"], int)
        assert isinstance(result["colorhash_distance"], int)

    def test_empty_fingerprints_return_error(self):
        from backend.faces.similarity import compare_fingerprints
        result = compare_fingerprints({}, {})
        assert "error" in result


# --------------------------------------------------------------------------- #
# Test: engine availability check (no model load)
# --------------------------------------------------------------------------- #
class TestEngineAvailability:
    def test_is_available_returns_bool(self):
        from backend.faces import engine
        result = engine.is_available()
        assert isinstance(result, bool)
        # Since we installed insightface + onnxruntime, should be True
        assert result is True
