from __future__ import annotations

import pytest

from backend.normalization.domains import (
    is_personal_domain,
    normalize_domain,
    normalize_hostname,
)
from backend.normalization.urls import canonicalize_url


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com/Foo",
        "https://www.github.com/foo/",
        "github.com/foo?utm_source=test#about",
        "http://github.com/foo",
    ],
)
def test_github_profile_url_variants_have_one_canonical_form(raw: str) -> None:
    assert canonicalize_url(raw) == "https://github.com/foo"


def test_url_normalization_handles_platform_aliases_ports_and_query_order() -> None:
    assert canonicalize_url("https://old.reddit.com/u/Alice/") == (
        "https://reddit.com/user/alice"
    )
    assert canonicalize_url("http://Example.com:80/about/?z=2&utm_x=y&a=1#top") == (
        "https://example.com/about?a=1&z=2"
    )


@pytest.mark.parametrize("raw", ["javascript:alert(1)", "ftp://example.com/a"])
def test_url_normalization_rejects_non_web_schemes(raw: str) -> None:
    with pytest.raises(ValueError):
        canonicalize_url(raw)


def test_url_normalization_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError):
        canonicalize_url("https://user:secret@example.com/profile")


def test_domain_normalization_uses_registrable_domain() -> None:
    assert normalize_hostname("https://www.blog.example.co.uk/a") == "blog.example.co.uk"
    assert normalize_domain("https://www.blog.example.co.uk/a?utm_x=y") == "example.co.uk"
    assert normalize_domain("sub.example.com") == "example.com"


def test_platform_domains_are_not_personal_identity_domains() -> None:
    assert not is_personal_domain("github.com")
    assert is_personal_domain("kartik.dev")
