"""Deterministic normalization primitives used by the correlation engine."""

from .domains import is_personal_domain, normalize_domain, normalize_hostname
from .names import compact_name, name_similarity, name_tokens, normalize_name
from .profiles import (
    NormalizedProfile,
    TemporalClaim,
    deduplicate_profiles,
    normalize_profile,
    profile_dedupe_key,
)
from .urls import canonicalize_url
from .usernames import (
    compact_username,
    normalize_username,
    username_similarity,
    username_tokens,
)

__all__ = [
    "NormalizedProfile",
    "TemporalClaim",
    "canonicalize_url",
    "compact_name",
    "compact_username",
    "deduplicate_profiles",
    "is_personal_domain",
    "name_similarity",
    "name_tokens",
    "normalize_domain",
    "normalize_hostname",
    "normalize_name",
    "normalize_profile",
    "normalize_username",
    "profile_dedupe_key",
    "username_similarity",
    "username_tokens",
]
