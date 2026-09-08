"""Indexed candidate blocking for normalized profiles."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

from backend.normalization.names import name_similarity, name_tokens
from backend.normalization.profiles import NormalizedProfile
from backend.normalization.usernames import username_similarity

from .features import BlockingReason


@dataclass(frozen=True, slots=True)
class CandidatePair:
    left: NormalizedProfile
    right: NormalizedProfile
    reasons: tuple[BlockingReason, ...]

    @property
    def pair_key(self) -> tuple[str, str]:
        return tuple(sorted((self.left.profile_id, self.right.profile_id)))  # type: ignore[return-value]


def generate_candidate_pairs(
    profiles: Iterable[NormalizedProfile],
    *,
    username_threshold: float = 0.78,
    name_threshold: float = 0.86,
    semantic_neighbors: Iterable[tuple[str, str]] = (),
    image_neighbors: Iterable[tuple[str, str]] = (),
) -> tuple[CandidatePair, ...]:
    """Generate plausible comparison pairs using indexed blocking features.

    Semantic/image nearest-neighbour pairs are accepted as inputs because the
    PostgreSQL/pgvector repository performs those searches. This pure function
    never performs a full embedding scan.
    """

    profile_list = tuple(profiles)
    profile_by_id = {profile.profile_id: profile for profile in profile_list}
    if len(profile_by_id) != len(profile_list):
        raise ValueError("profile IDs must be unique before candidate blocking")

    reasons: dict[tuple[str, str], set[BlockingReason]] = defaultdict(set)

    def add_pair(left_id: str, right_id: str, reason: BlockingReason) -> None:
        if left_id == right_id or left_id not in profile_by_id or right_id not in profile_by_id:
            return
        left = profile_by_id[left_id]
        right = profile_by_id[right_id]
        if left.platform == right.platform and left.canonical_url == right.canonical_url:
            return
        reasons[_pair_key(left_id, right_id)].add(reason)

    _block_exact_values(
        profile_list,
        lambda profile: profile.compact_username,
        lambda left, right: add_pair(left, right, BlockingReason.EXACT_USERNAME),
    )
    _block_exact_values(
        profile_list,
        lambda profile: profile.normalized_display_name,
        lambda left, right: add_pair(left, right, BlockingReason.SIMILAR_NAME),
    )
    _block_multivalues(
        profile_list,
        lambda profile: profile.personal_domains,
        lambda left, right: add_pair(left, right, BlockingReason.SHARED_DOMAIN),
    )
    _block_multivalues(
        profile_list,
        lambda profile: profile.external_links,
        lambda left, right: add_pair(left, right, BlockingReason.SHARED_EXTERNAL_URL),
    )
    _block_exact_values(
        profile_list,
        lambda profile: profile.avatar_sha256 or profile.avatar_phash or "",
        lambda left, right: add_pair(left, right, BlockingReason.SHARED_AVATAR),
    )

    # A profile directly referencing another candidate is an explicit block.
    profile_ids_by_url = {profile.canonical_url: profile.profile_id for profile in profile_list}
    for profile in profile_list:
        for link in profile.external_links:
            target = profile_ids_by_url.get(link)
            if target:
                add_pair(profile.profile_id, target, BlockingReason.DIRECT_CROSS_LINK)

    _block_fuzzy_usernames(profile_list, add_pair, username_threshold)
    _block_fuzzy_names(profile_list, add_pair, name_threshold)
    _block_contextual_names(profile_list, add_pair, name_threshold)

    for left_id, right_id in semantic_neighbors:
        add_pair(left_id, right_id, BlockingReason.SEMANTIC_NEIGHBOR)
    for left_id, right_id in image_neighbors:
        add_pair(left_id, right_id, BlockingReason.IMAGE_NEIGHBOR)

    result = []
    for pair_key, pair_reasons in sorted(reasons.items()):
        left_id, right_id = pair_key
        result.append(
            CandidatePair(
                left=profile_by_id[left_id],
                right=profile_by_id[right_id],
                reasons=tuple(sorted(pair_reasons, key=str)),
            )
        )
    return tuple(result)


def _block_exact_values(profiles, value_getter, add_pair) -> None:
    index: dict[str, list[str]] = defaultdict(list)
    for profile in profiles:
        value = value_getter(profile)
        if value:
            index[value].append(profile.profile_id)
    for profile_ids in index.values():
        for left_id, right_id in combinations(sorted(set(profile_ids)), 2):
            add_pair(left_id, right_id)


def _block_multivalues(profiles, values_getter, add_pair) -> None:
    index: dict[str, list[str]] = defaultdict(list)
    for profile in profiles:
        for value in values_getter(profile):
            if value:
                index[value].append(profile.profile_id)
    for profile_ids in index.values():
        for left_id, right_id in combinations(sorted(set(profile_ids)), 2):
            add_pair(left_id, right_id)


def _block_fuzzy_usernames(profiles, add_pair, threshold: float) -> None:
    # Prefix + length buckets drastically constrain comparisons while allowing
    # separator changes and a small edit distance.
    buckets: dict[str, list[NormalizedProfile]] = defaultdict(list)
    for profile in profiles:
        compact = profile.compact_username
        if compact:
            buckets[compact[:2]].append(profile)
    for bucket in buckets.values():
        for left, right in combinations(bucket, 2):
            if abs(len(left.compact_username) - len(right.compact_username)) > 3:
                continue
            if username_similarity(left.username, right.username) >= threshold:
                add_pair(left.profile_id, right.profile_id, BlockingReason.SIMILAR_USERNAME)


def _block_fuzzy_names(profiles, add_pair, threshold: float) -> None:
    # Profiles only enter the same bucket when a normalized name token overlaps.
    token_index: dict[str, list[NormalizedProfile]] = defaultdict(list)
    for profile in profiles:
        for token in set(name_tokens(profile.display_name)):
            if len(token) >= 2:
                token_index[token].append(profile)
    compared: set[tuple[str, str]] = set()
    for bucket in token_index.values():
        for left, right in combinations(bucket, 2):
            key = _pair_key(left.profile_id, right.profile_id)
            if key in compared:
                continue
            compared.add(key)
            if name_similarity(left.display_name, right.display_name) >= threshold:
                add_pair(left.profile_id, right.profile_id, BlockingReason.SIMILAR_NAME)


def _block_contextual_names(profiles, add_pair, threshold: float) -> None:
    organization_index: dict[str, list[NormalizedProfile]] = defaultdict(list)
    location_index: dict[str, list[NormalizedProfile]] = defaultdict(list)
    for profile in profiles:
        if profile.normalized_organization:
            organization_index[profile.normalized_organization].append(profile)
        if profile.normalized_location:
            location_index[profile.normalized_location].append(profile)

    for reason, index in (
        (BlockingReason.ORGANIZATION_AND_NAME, organization_index),
        (BlockingReason.LOCATION_AND_NAME, location_index),
    ):
        for bucket in index.values():
            for left, right in combinations(bucket, 2):
                if name_similarity(left.display_name, right.display_name) >= threshold:
                    add_pair(left.profile_id, right.profile_id, reason)


def _pair_key(left_id: str, right_id: str) -> tuple[str, str]:
    return tuple(sorted((left_id, right_id)))  # type: ignore[return-value]
