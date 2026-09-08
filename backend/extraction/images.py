"""Evidence from precomputed image hashes and bounded similarity metrics."""

from __future__ import annotations

from backend.correlation.features import Direction, EvidenceFamily, SignalType
from backend.normalization.profiles import NormalizedProfile

from ._shared import evidence


def perceptual_hash_similarity(left: str | None, right: str | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    try:
        left_value = int(left, 16)
        right_value = int(right, 16)
    except ValueError:
        return 0.0
    bit_count = len(left) * 4
    return 1.0 - ((left_value ^ right_value).bit_count() / bit_count)


def extract_image_evidence(
    left: NormalizedProfile,
    right: NormalizedProfile,
    *,
    image_similarity: float | None = None,
    face_similarity: float | None = None,
) -> tuple:
    results = []
    if left.avatar_sha256 and right.avatar_sha256 and left.avatar_sha256 == right.avatar_sha256:
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.EXACT_AVATAR,
                direction=Direction.SUPPORT,
                score=1.0,
                reliability=0.96,
                family=EvidenceFamily.IMAGE_IDENTITY,
                explanation="Both profiles use the exact same avatar file hash.",
                source_key=f"avatar-sha256:{left.avatar_sha256}",
            )
        )
    else:
        phash_similarity = perceptual_hash_similarity(left.avatar_phash, right.avatar_phash)
        if phash_similarity >= 0.85:
            results.append(
                evidence(
                    left,
                    right,
                    signal_type=SignalType.IMAGE_SIMILARITY,
                    direction=Direction.SUPPORT,
                    score=phash_similarity,
                    reliability=0.82,
                    family=EvidenceFamily.IMAGE_IDENTITY,
                    explanation="The profile avatars have closely matching perceptual hashes.",
                    source_key=f"avatar-phash:{left.profile_id}:{right.profile_id}",
                    metadata={"similarity": phash_similarity, "method": "phash"},
                )
            )

    if image_similarity is not None and image_similarity >= 0.8:
        results.append(
            evidence(
                left,
                right,
                signal_type=SignalType.IMAGE_SIMILARITY,
                direction=Direction.SUPPORT,
                score=image_similarity,
                reliability=0.75,
                family=EvidenceFamily.IMAGE_IDENTITY,
                explanation="A dedicated image model found the public avatars similar.",
                source_key=f"image-model:{left.profile_id}:{right.profile_id}",
                metadata={"similarity": image_similarity, "method": "embedding"},
            )
        )

    if face_similarity is not None:
        if face_similarity >= 0.78:
            results.append(
                evidence(
                    left,
                    right,
                    signal_type=SignalType.FACE_SIMILARITY,
                    direction=Direction.SUPPORT,
                    score=face_similarity,
                    reliability=0.7,
                    family=EvidenceFamily.IMAGE_IDENTITY,
                    explanation="A bounded face comparison found similar candidate faces.",
                    source_key=f"face-model:{left.profile_id}:{right.profile_id}",
                    metadata={"similarity": face_similarity},
                )
            )
        elif face_similarity <= 0.25:
            results.append(
                evidence(
                    left,
                    right,
                    signal_type=SignalType.DIFFERENT_FACE,
                    direction=Direction.CONTRADICT,
                    score=1.0 - face_similarity,
                    reliability=0.75,
                    family=EvidenceFamily.IMAGE_IDENTITY,
                    explanation="A bounded face comparison found clearly dissimilar faces.",
                    source_key=f"face-model:{left.profile_id}:{right.profile_id}",
                    metadata={"similarity": face_similarity},
                )
            )
    return tuple(results)
