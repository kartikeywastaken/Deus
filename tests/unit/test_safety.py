"""Pure safety and advisory validation tests, not fabricated collection."""

import pytest

from backend.connectors.safe_http import validate_url
from backend.embeddings.text import _validated_vector
from backend.investigation.adviser import Advice


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://127.0.0.1",
        "https://[::1]",
        "https://169.254.169.254/latest",
        "https://user:pass@example.com",
        "https://example.com:8443",
        "file:///etc/passwd",
        "https://localhost",
    ],
)
def test_private_or_unsafe_urls_are_rejected(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize("vector", [[0.0] * 384, [float("nan")] * 384, [float("inf")] * 384])
def test_invalid_vectors_are_rejected(vector):
    with pytest.raises(ValueError):
        _validated_vector(vector, 384)


def test_ai_cannot_add_evidence_or_scores():
    with pytest.raises(ValueError):
        Advice.model_validate({"pivot_id": 0, "reason": "reason", "score": 1.0})
