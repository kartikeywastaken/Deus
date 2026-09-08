"""Username normalization without platform-specific assumptions.

The normal form preserves separators because they may be meaningful on a
platform.  The compact form is deliberately more permissive and is intended
only for candidate comparison, never as a globally unique identifier.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_USERNAME_SEPARATORS_RE = re.compile(r"[\s._\-–—]+", re.UNICODE)


def normalize_username(value: str | None) -> str:
    """Return a stable, case-insensitive username representation.

    A single leading ``@`` is presentation syntax and is removed. Unicode is
    normalized with NFKC and Unicode case-folding. Internal whitespace is
    removed because supported account handles cannot meaningfully contain it.
    Other punctuation is retained: stripping it in the canonical form could
    conflate two distinct platform accounts.
    """

    if value is None:
        return ""

    normalized = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    return "".join(character for character in normalized if not character.isspace())


def compact_username(value: str | None) -> str:
    """Return the alphanumeric comparison form of a username."""

    return "".join(character for character in normalize_username(value) if character.isalnum())


def username_tokens(value: str | None) -> tuple[str, ...]:
    """Split a username into stable separator and alpha/numeric tokens."""

    normalized = normalize_username(value)
    if not normalized:
        return ()

    coarse = [part for part in _USERNAME_SEPARATORS_RE.split(normalized) if part]
    tokens: list[str] = []
    for part in coarse:
        # ``alice42dev`` becomes ``alice``, ``42``, ``dev``. Token boundaries
        # are useful blocking features but never identity proof.
        tokens.extend(re.findall(r"[^\W\d_]+|\d+", part, flags=re.UNICODE))
    return tuple(tokens)


def username_similarity(left: str | None, right: str | None) -> float:
    """Return a deterministic username similarity in the inclusive [0, 1]."""

    left_normalized = normalize_username(left)
    right_normalized = normalize_username(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0

    left_compact = compact_username(left_normalized)
    right_compact = compact_username(right_normalized)
    if not left_compact or not right_compact:
        return 0.0

    compact_ratio = SequenceMatcher(None, left_compact, right_compact).ratio()
    canonical_ratio = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    token_overlap = _token_overlap(username_tokens(left), username_tokens(right))
    return round(max(compact_ratio, canonical_ratio, token_overlap), 6)


def _token_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    if not left or not right:
        return 0.0
    left_set = set(left)
    right_set = set(right)
    return len(left_set & right_set) / len(left_set | right_set)
