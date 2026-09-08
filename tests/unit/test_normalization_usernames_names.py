from __future__ import annotations

import pytest

from backend.normalization.names import compact_name, name_similarity, normalize_name
from backend.normalization.usernames import (
    compact_username,
    normalize_username,
    username_similarity,
    username_tokens,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" @Kartikey_Was-Taken ", "kartikey_was-taken"),
        ("Ａlice Dev", "alicedev"),
    ],
)
def test_normalize_username(raw: str, expected: str) -> None:
    assert normalize_username(raw) == expected


def test_username_comparison_keeps_canonical_and_compact_forms_separate() -> None:
    assert normalize_username("Alice.Dev") == "alice.dev"
    assert compact_username("Alice.Dev") == "alicedev"
    assert username_tokens("alice_dev42") == ("alice", "dev", "42")
    assert username_similarity("Alice.Dev", "alice-dev") == 1.0


def test_empty_usernames_do_not_match() -> None:
    assert normalize_username(None) == ""
    assert username_similarity(None, "alice") == 0.0
    assert username_similarity("", "") == 0.0


def test_name_normalization_handles_unicode_punctuation_and_whitespace() -> None:
    assert normalize_name("  José   D’Silva  ") == "jose d silva"
    assert compact_name("José D'Silva") == "josedsilva"


def test_name_similarity_tolerates_token_order_but_not_unrelated_names() -> None:
    assert name_similarity("Karthik Sharma", "Sharma, Karthik") == 1.0
    assert name_similarity("Karthik Sharma", "Elena Petrov") < 0.4
