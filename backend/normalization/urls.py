"""Web and supported-platform URL canonicalization."""

from __future__ import annotations

import re
from posixpath import normpath
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMETERS = {
    "dclid",
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "ref_src",
}
_HOST_ALIASES = {
    "mobile.twitter.com": "x.com",
    "twitter.com": "x.com",
    "www.twitter.com": "x.com",
    "www.x.com": "x.com",
    "old.reddit.com": "reddit.com",
    "www.reddit.com": "reddit.com",
}
_CASE_INSENSITIVE_PROFILE_HOSTS = {
    "dev.to",
    "facebook.com",
    "github.com",
    "gitlab.com",
    "instagram.com",
    "linkedin.com",
    "reddit.com",
    "stackoverflow.com",
    "x.com",
}


def canonicalize_url(value: str | None) -> str:
    """Return a canonical public HTTP(S) URL.

    The result intentionally uses HTTPS for identity/deduplication purposes,
    strips fragments and known tracking parameters, normalizes default ports,
    and applies a small set of well-understood platform aliases.

    Raises:
        ValueError: if *value* is empty, is not HTTP(S), or has no hostname.
    """

    if value is None or not str(value).strip():
        raise ValueError("URL cannot be empty")

    raw = str(value).strip()
    if raw.startswith("//"):
        raw = f"https:{raw}"
    elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = f"https://{raw}"

    parsed = urlsplit(raw)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ValueError("only HTTP(S) URLs can be canonicalized")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not accepted")

    host = _canonical_host(parsed.hostname)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL contains an invalid port") from exc

    include_port = port is not None and port not in {80, 443}
    netloc = f"{host}:{port}" if include_port else host

    path = _canonical_path(host, parsed.path)
    query = _canonical_query(parsed.query)
    return urlunsplit(("https", netloc, path, query, ""))


def _canonical_host(host: str) -> str:
    normalized = host.rstrip(".").casefold()
    try:
        normalized = normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("URL hostname is not valid IDNA") from exc
    if normalized.startswith("www."):
        normalized = normalized[4:]
    return _HOST_ALIASES.get(normalized, normalized)


def _canonical_path(host: str, raw_path: str) -> str:
    decoded = unquote(raw_path or "")
    decoded = re.sub(r"/{2,}", "/", decoded)
    normalized = normpath(decoded) if decoded else ""
    if normalized in {".", "/"}:
        normalized = ""
    elif not normalized.startswith("/"):
        normalized = f"/{normalized}"

    # Reddit treats /u/name and /user/name as the same public profile.
    if host == "reddit.com":
        normalized = re.sub(r"^/u/", "/user/", normalized, flags=re.IGNORECASE)

    if host in _CASE_INSENSITIVE_PROFILE_HOSTS:
        normalized = normalized.casefold()

    # Preserve URL separators and common profile punctuation while safely
    # escaping whitespace or other unsafe characters.
    return quote(normalized.rstrip("/"), safe="/%:@._~!$&'()*+,;=-")


def _canonical_query(raw_query: str) -> str:
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(raw_query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered.startswith("utm_") or lowered in _TRACKING_PARAMETERS:
            continue
        kept.append((key, value))
    return urlencode(sorted(kept), doseq=True)
