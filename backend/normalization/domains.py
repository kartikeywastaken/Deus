"""Hostname and registrable-domain normalization."""

from __future__ import annotations

import re
from ipaddress import ip_address
from urllib.parse import urlsplit

# A deliberately small offline fallback for common multi-label public suffixes.
# Deployments already depend on tldextract and can use its bundled PSL snapshot;
# this list keeps the pure normalization package deterministic in minimal tests.
_COMMON_MULTI_LABEL_SUFFIXES = {
    "ac.in",
    "ac.jp",
    "ac.uk",
    "asn.au",
    "co.in",
    "co.jp",
    "co.nz",
    "co.uk",
    "com.au",
    "com.br",
    "com.cn",
    "com.mx",
    "com.sg",
    "edu.au",
    "firm.in",
    "gen.in",
    "gov.uk",
    "id.au",
    "ind.in",
    "me.uk",
    "net.au",
    "net.in",
    "net.nz",
    "ne.jp",
    "org.au",
    "org.in",
    "org.nz",
    "org.uk",
}

_PLATFORM_DOMAINS = {
    "dev.to",
    "facebook.com",
    "github.com",
    "gitlab.com",
    "instagram.com",
    "linkedin.com",
    "medium.com",
    "reddit.com",
    "stackoverflow.com",
    "tiktok.com",
    "x.com",
    "youtube.com",
}


def normalize_hostname(value: str | None) -> str:
    """Extract and normalize a hostname while retaining meaningful subdomains."""

    host = _extract_host(value)
    if not host:
        return ""
    host = host.rstrip(".").casefold()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("domain is not valid IDNA") from exc
    return host[4:] if host.startswith("www.") else host


def normalize_domain(value: str | None) -> str:
    """Return the registrable comparison domain for a URL or hostname."""

    host = normalize_hostname(value)
    if not host:
        return ""
    try:
        ip_address(host)
        return host
    except ValueError:
        pass

    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return host
    suffix = ".".join(labels[-2:])
    if suffix in _COMMON_MULTI_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def is_personal_domain(value: str | None) -> bool:
    """Return whether a domain is suitable as personal-web identity evidence."""

    domain = normalize_domain(value)
    if not domain or domain in _PLATFORM_DOMAINS:
        return False
    if domain == "localhost" or not _looks_like_domain_or_ip(domain):
        return False
    return True


def _extract_host(value: str | None) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    candidate = raw if "://" in raw or raw.startswith("//") else f"//{raw}"
    parsed = urlsplit(candidate)
    return parsed.hostname or ""


def _looks_like_domain_or_ip(value: str) -> bool:
    try:
        ip_address(value)
        return True
    except ValueError:
        return bool(re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", value))
