"""Recognize account URLs, never posts, repositories, or generic platform navigation."""

import re
from urllib.parse import urlsplit

from backend.normalization.urls import canonicalize_url

PATTERNS = {
    "github.com": ("github", r"/([\w-]+)"),
    "gitlab.com": ("gitlab", r"/([\w.-]+)"),
    "instagram.com": ("instagram", r"/([\w.]+)"),
    "linkedin.com": ("linkedin", r"/in/([\w%-]+)"),
    "facebook.com": ("facebook", r"/([\w.]+)"),
    "x.com": ("twitter", r"/(\w+)"),
    "reddit.com": ("reddit", r"/user/([\w-]+)"),
    "youtube.com": ("youtube", r"/(@[\w.-]+|channel/[\w-]+)"),
    "tiktok.com": ("tiktok", r"/@([\w.]+)"),
    "twitch.tv": ("twitch", r"/(\w+)"),
    "pinterest.com": ("pinterest", r"/(\w+)"),
    "dev.to": ("dev.to", r"/([\w-]+)"),
    "medium.com": ("medium", r"/@([\w.-]+)"),
    "t.me": ("telegram", r"/(\w+)"),
    "keybase.io": ("keybase", r"/(\w+)"),
    "mastodon.social": ("mastodon", r"/@([\w.-]+)"),
}
RESERVED = {
    "login",
    "signup",
    "about",
    "explore",
    "settings",
    "privacy",
    "terms",
    "home",
    "search",
    "share",
    "intent",
    "features",
    "pricing",
    "help",
}


def profile_link(value):
    try:
        url = canonicalize_url(value)
        parsed = urlsplit(url)
        platform, pattern = PATTERNS.get(parsed.hostname, (None, ""))
        match = re.fullmatch(pattern, parsed.path) if platform else None
        if match and match[1].casefold() not in RESERVED and not parsed.query:
            return platform, match[1].removeprefix("@"), url
    except ValueError:
        pass
    return None


def declared_profiles(result):
    """Retain source-declared accounts even when the destination blocks collection."""
    from .schemas import CandidateProfile

    links = [(p.canonical_url, link) for p in result.profiles for link in p.external_links]
    links += [
        (o.profile_url, o.value)
        for o in result.observations
        if o.signal_type == "PUBLIC_EXTERNAL_LINK" and isinstance(o.value, str)
    ]
    seen = {canonicalize_url(p.canonical_url) for p in result.profiles}
    added = []
    for source, link in links:
        target = profile_link(link)
        if target and target[2] not in seen:
            seen.add(target[2])
            added.append(
                CandidateProfile(
                    platform=target[0],
                    username=target[1],
                    canonical_url=target[2],
                    source_url=source,
                    discovered_by=[result.connector],
                    raw={
                        "discovery_kind": "PUBLICLY_LINKED",
                        "linked_from": source,
                        "destination_existence": "UNVERIFIED",
                    },
                )
            )
    return result.model_copy(update={"profiles": result.profiles + added})
