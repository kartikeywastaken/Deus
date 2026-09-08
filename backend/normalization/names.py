"""Human-name normalization and conservative lexical comparison."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_SPACE_RE = re.compile(r"\s+")


def normalize_name(value: str | None) -> str:
    """Normalize a display name for comparison.

    Diacritics are removed from the comparison representation so that common
    transliterations such as ``Jose`` and ``José`` can be candidates. Original
    display values must still be retained by callers for reporting.
    """

    if value is None:
        return ""

    decomposed = unicodedata.normalize("NFKD", str(value)).casefold()
    without_marks = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    punctuation_as_space = "".join(
        character if character.isalnum() else " " for character in without_marks
    )
    return _SPACE_RE.sub(" ", punctuation_as_space).strip()


def name_tokens(value: str | None) -> tuple[str, ...]:
    normalized = normalize_name(value)
    return tuple(normalized.split()) if normalized else ()


def compact_name(value: str | None) -> str:
    return "".join(name_tokens(value))


def name_similarity(left: str | None, right: str | None) -> float:
    """Compare names while tolerating token order and punctuation changes."""

    left_normalized = normalize_name(left)
    right_normalized = normalize_name(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0

    left_tokens = name_tokens(left_normalized)
    right_tokens = name_tokens(right_normalized)
    left_set = set(left_tokens)
    right_set = set(right_tokens)
    token_jaccard = len(left_set & right_set) / len(left_set | right_set)

    ordered_ratio = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    sorted_ratio = SequenceMatcher(
        None,
        " ".join(sorted(left_tokens)),
        " ".join(sorted(right_tokens)),
    ).ratio()
    return round(max(token_jaccard, ordered_ratio, sorted_ratio), 6)
