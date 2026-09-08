"""Database-independent normalized profile records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, datetime
from typing import Any

from .domains import is_personal_domain, normalize_domain
from .names import normalize_name
from .urls import canonicalize_url
from .usernames import compact_username as make_compact_username
from .usernames import normalize_username


@dataclass(frozen=True, slots=True)
class TemporalClaim:
    """A normalized assertion bounded by an optional validity interval."""

    value: str
    normalized_value: str
    start: datetime | None = None
    end: datetime | None = None
    confidence: float = 1.0
    exclusive: bool = False

    def overlaps(self, other: TemporalClaim) -> bool:
        """Return whether two closed-open-ish intervals can overlap.

        Unknown bounds are treated as unbounded. This method says only that the
        dates overlap; extractors decide whether differing claims contradict.
        """

        left_start = self.start or datetime.min.replace(tzinfo=UTC)
        left_end = self.end or datetime.max.replace(tzinfo=UTC)
        right_start = other.start or datetime.min.replace(tzinfo=UTC)
        right_end = other.end or datetime.max.replace(tzinfo=UTC)
        return left_start <= right_end and right_start <= left_end


@dataclass(frozen=True, slots=True)
class NormalizedProfile:
    """Canonical profile data accepted by deterministic correlation functions."""

    profile_id: str
    platform: str
    canonical_url: str
    platform_account_id: str | None = None
    username: str | None = None
    normalized_username: str = ""
    compact_username: str = ""
    display_name: str | None = None
    normalized_display_name: str = ""
    bio: str | None = None
    location: str | None = None
    normalized_location: str = ""
    organization: str | None = None
    normalized_organization: str = ""
    external_links: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    personal_domains: tuple[str, ...] = ()
    primary_domain: str | None = None
    avatar_sha256: str | None = None
    avatar_phash: str | None = None
    bio_embedding: tuple[float, ...] | None = None
    image_embedding: tuple[float, ...] | None = None
    projects: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    location_claims: tuple[TemporalClaim, ...] = ()
    organization_claims: tuple[TemporalClaim, ...] = ()
    source_observation_ids: tuple[str, ...] = ()


def profile_dedupe_key(profile: NormalizedProfile) -> tuple[str, str, str]:
    """Return the preferred stable key for one canonical platform profile."""

    if profile.platform_account_id:
        return (profile.platform, "account", profile.platform_account_id)
    return (profile.platform, "url", profile.canonical_url)


def deduplicate_profiles(
    profiles: Sequence[NormalizedProfile],
) -> tuple[NormalizedProfile, ...]:
    """Merge repeat observations of the same platform account.

    Account IDs win when present; canonical platform URLs provide the fallback.
    Cross-platform handles are deliberately never deduplicated.
    """

    deduplicated: list[NormalizedProfile] = []
    positions_by_account: dict[tuple[str, str], int] = {}
    positions_by_url: dict[tuple[str, str], int] = {}

    for profile in profiles:
        account_key = (
            (profile.platform, profile.platform_account_id) if profile.platform_account_id else None
        )
        url_key = (profile.platform, profile.canonical_url)
        position = positions_by_account.get(account_key) if account_key else None
        if position is None:
            position = positions_by_url.get(url_key)

        if position is None:
            position = len(deduplicated)
            deduplicated.append(profile)
        else:
            deduplicated[position] = _merge_profiles(deduplicated[position], profile)

        merged = deduplicated[position]
        positions_by_url[(merged.platform, merged.canonical_url)] = position
        if merged.platform_account_id:
            positions_by_account[(merged.platform, merged.platform_account_id)] = position

    return tuple(deduplicated)


def normalize_profile(value: Mapping[str, Any] | Any) -> NormalizedProfile:
    """Normalize a mapping, dataclass-like object, or Pydantic model.

    This adapter deliberately has no dependency on ORM or API schemas. That
    keeps normalization and correlation usable in workers and unit tests.
    """

    data = _as_mapping(value)
    platform = str(data.get("platform") or "unknown").strip().casefold()
    canonical_url = canonicalize_url(data.get("canonical_url") or data.get("profile_url"))
    account_id = _optional_string(data.get("platform_account_id"))

    username = _optional_string(data.get("username"))
    normalized_username = normalize_username(username)
    display_name = _optional_string(data.get("display_name") or data.get("name"))

    external_links = _normalize_links(data.get("external_links") or data.get("website_urls") or ())
    domains = tuple(dict.fromkeys(normalize_domain(link) for link in external_links))
    domains = tuple(domain for domain in domains if domain)
    personal_domains = tuple(domain for domain in domains if is_personal_domain(domain))

    primary_domain_value = data.get("primary_domain")
    primary_domain = normalize_domain(primary_domain_value) if primary_domain_value else None

    location = _optional_string(data.get("location") or data.get("current_location"))
    organization = _optional_string(
        data.get("organization") or data.get("current_organization") or data.get("employer")
    )

    profile_id = _optional_string(data.get("profile_id") or data.get("id"))
    if not profile_id:
        stable_identifier = account_id or canonical_url
        profile_id = f"{platform}:{stable_identifier}"

    return NormalizedProfile(
        profile_id=profile_id,
        platform=platform,
        platform_account_id=account_id,
        username=username,
        normalized_username=normalized_username,
        compact_username=make_compact_username(username),
        display_name=display_name,
        normalized_display_name=normalize_name(display_name),
        canonical_url=canonical_url,
        bio=_optional_string(data.get("bio") or data.get("current_bio")),
        location=location,
        normalized_location=normalize_name(location),
        organization=organization,
        normalized_organization=normalize_name(organization),
        external_links=external_links,
        domains=domains,
        personal_domains=personal_domains,
        primary_domain=primary_domain,
        avatar_sha256=_normalized_hash(data.get("avatar_sha256")),
        avatar_phash=_normalized_hash(data.get("avatar_phash") or data.get("perceptual_hash")),
        bio_embedding=_float_tuple(data.get("bio_embedding")),
        image_embedding=_float_tuple(data.get("image_embedding")),
        projects=_normalized_string_tuple(data.get("projects")),
        topics=_normalized_string_tuple(data.get("topics")),
        location_claims=_normalize_claims(data.get("location_claims"), normalize_name),
        organization_claims=_normalize_claims(data.get("organization_claims"), normalize_name),
        source_observation_ids=_string_tuple(data.get("source_observation_ids")),
    )


def _merge_profiles(
    left: NormalizedProfile,
    right: NormalizedProfile,
) -> NormalizedProfile:
    if left.platform != right.platform:
        raise ValueError("cannot deduplicate profiles from different platforms")
    if (
        left.platform_account_id
        and right.platform_account_id
        and left.platform_account_id != right.platform_account_id
    ):
        raise ValueError("canonical URL collision between different platform account IDs")

    def prefer(left_value: Any, right_value: Any) -> Any:
        return left_value if left_value not in (None, "", (), []) else right_value

    return replace(
        left,
        platform_account_id=prefer(left.platform_account_id, right.platform_account_id),
        username=prefer(left.username, right.username),
        normalized_username=prefer(left.normalized_username, right.normalized_username),
        compact_username=prefer(left.compact_username, right.compact_username),
        display_name=prefer(left.display_name, right.display_name),
        normalized_display_name=prefer(left.normalized_display_name, right.normalized_display_name),
        bio=prefer(left.bio, right.bio),
        location=prefer(left.location, right.location),
        normalized_location=prefer(left.normalized_location, right.normalized_location),
        organization=prefer(left.organization, right.organization),
        normalized_organization=prefer(left.normalized_organization, right.normalized_organization),
        external_links=tuple(dict.fromkeys(left.external_links + right.external_links)),
        domains=tuple(dict.fromkeys(left.domains + right.domains)),
        personal_domains=tuple(dict.fromkeys(left.personal_domains + right.personal_domains)),
        primary_domain=prefer(left.primary_domain, right.primary_domain),
        avatar_sha256=prefer(left.avatar_sha256, right.avatar_sha256),
        avatar_phash=prefer(left.avatar_phash, right.avatar_phash),
        bio_embedding=prefer(left.bio_embedding, right.bio_embedding),
        image_embedding=prefer(left.image_embedding, right.image_embedding),
        projects=tuple(dict.fromkeys(left.projects + right.projects)),
        topics=tuple(dict.fromkeys(left.topics + right.topics)),
        location_claims=tuple(dict.fromkeys(left.location_claims + right.location_claims)),
        organization_claims=tuple(
            dict.fromkeys(left.organization_claims + right.organization_claims)
        ),
        source_observation_ids=tuple(
            dict.fromkeys(left.source_observation_ids + right.source_observation_ids)
        ),
    )


def _as_mapping(value: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return vars(value)
    raise TypeError("profile must be a mapping or object with fields")


def _normalize_links(values: Sequence[str] | str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    normalized: list[str] = []
    for value in values:
        try:
            canonical = canonicalize_url(value)
        except (TypeError, ValueError):
            continue
        if canonical not in normalized:
            normalized.append(canonical)
    return tuple(normalized)


def _normalize_claims(values: Any, normalizer: Any) -> tuple[TemporalClaim, ...]:
    if not values:
        return ()
    claims: list[TemporalClaim] = []
    for item in values:
        if isinstance(item, TemporalClaim):
            claims.append(item)
            continue
        if isinstance(item, str):
            claims.append(TemporalClaim(item, normalizer(item)))
            continue
        if not isinstance(item, Mapping) or not item.get("value"):
            continue
        raw_value = str(item["value"])
        claims.append(
            TemporalClaim(
                value=raw_value,
                normalized_value=normalizer(raw_value),
                start=_coerce_datetime(item.get("start")),
                end=_coerce_datetime(item.get("end")),
                confidence=_bounded_float(item.get("confidence", 1.0)),
                exclusive=bool(item.get("exclusive", False)),
            )
        )
    return tuple(claims)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def _float_tuple(value: Any) -> tuple[float, ...] | None:
    if value is None:
        return None
    result = tuple(float(item) for item in value)
    return result or None


def _normalized_string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(normalize_name(item) for item in _string_tuple(value)))


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if item is not None and str(item).strip())


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _normalized_hash(value: Any) -> str | None:
    result = _optional_string(value)
    return result.casefold() if result else None


def _bounded_float(value: Any) -> float:
    return min(1.0, max(0.0, float(value)))
