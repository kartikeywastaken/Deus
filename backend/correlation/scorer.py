"""Explainable, deterministic V0 correlation scoring."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from .features import (
    Classification,
    Direction,
    EvidenceContribution,
    EvidenceFamily,
    EvidenceSignal,
    PairAssessment,
    SignalType,
)

DEFAULT_WEIGHTS: Mapping[SignalType, float] = {
    SignalType.EMAIL_EXACT: 45.0,
    SignalType.DIRECT_PROFILE_LINK: 40.0,
    SignalType.SHARED_PERSONAL_DOMAIN: 30.0,
    SignalType.DOMAIN_EXACT: 30.0,
    SignalType.URL_EXACT: 25.0,
    SignalType.SHARED_IDENTIFIER: 25.0,
    SignalType.USERNAME_EXACT: 20.0,
    SignalType.REPOSITORY_RELATIONSHIP: 20.0,
    SignalType.USERNAME_SIMILARITY: 12.0,
    SignalType.DISPLAY_NAME_SIMILARITY: 10.0,
    SignalType.PROJECT_OVERLAP: 15.0,
    SignalType.ORGANIZATION_OVERLAP: 10.0,
    SignalType.BIO_SIMILARITY: 8.0,
    SignalType.TOPIC_OVERLAP: 3.0,
    SignalType.LOCATION_OVERLAP: 5.0,
    SignalType.EXACT_AVATAR: 20.0,
    SignalType.IMAGE_SIMILARITY: 16.0,
    SignalType.FACE_SIMILARITY: 16.0,
    SignalType.DIFFERENT_FACE: 40.0,
    SignalType.EXPLICIT_IDENTITY_CONFLICT: 40.0,
    SignalType.PERSONAL_DOMAIN_CONFLICT: 20.0,
    SignalType.BIOGRAPHICAL_CONTRADICTION: 15.0,
    SignalType.LOCATION_CONFLICT: 15.0,
    SignalType.ORGANIZATION_CONFLICT: 15.0,
}

_ANCHOR_SIGNALS = {
    SignalType.EMAIL_EXACT,
    SignalType.DIRECT_PROFILE_LINK,
    SignalType.SHARED_PERSONAL_DOMAIN,
    SignalType.DOMAIN_EXACT,
    SignalType.EXACT_AVATAR,
    SignalType.PROJECT_OVERLAP,
}


class CorrelationScorer:
    """Score evidence while counting at most one signal per evidence family."""

    def __init__(
        self,
        weights: Mapping[SignalType, float] | None = None,
        *,
        model_version: str = "deterministic-v0.1",
    ) -> None:
        self.weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
        self.model_version = model_version

    def score(
        self,
        evidence: Iterable[EvidenceSignal],
        *,
        left_profile_id: str | None = None,
        right_profile_id: str | None = None,
    ) -> PairAssessment:
        all_evidence = tuple(evidence)
        if all_evidence:
            pair_keys = {item.pair_key for item in all_evidence}
            if len(pair_keys) != 1:
                raise ValueError("all evidence must describe one profile pair")
            inferred_left, inferred_right = next(iter(pair_keys))
            left_profile_id = left_profile_id or inferred_left
            right_profile_id = right_profile_id or inferred_right
            if {left_profile_id, right_profile_id} != {inferred_left, inferred_right}:
                raise ValueError("explicit profile IDs do not match evidence")
        elif not left_profile_id or not right_profile_id:
            raise ValueError("profile IDs are required when scoring empty evidence")
        if left_profile_id == right_profile_id:
            raise ValueError("cannot score a profile against itself")

        selected = self._select_by_family(all_evidence)
        contributions = tuple(
            EvidenceContribution(item, self.contribution(item)) for item in selected
        )
        raw_score = round(sum(item.weighted_score for item in contributions), 6)
        normalized_score = round(max(-1.0, min(1.0, raw_score / 100.0)), 6)

        support_families = {
            item.evidence_family for item in selected if item.direction is Direction.SUPPORT
        }
        contradiction_families = {
            item.evidence_family for item in selected if item.direction is Direction.CONTRADICT
        }
        classification = self._classify(
            raw_score,
            selected,
            len(support_families),
        )

        # Track independent sources contributing to correlation
        independent_sources = set()
        matching_idents = []
        for item in selected:
            if item.direction is Direction.SUPPORT:
                src = item.source_key or item.metadata.get("source") or item.evidence_family.value
                independent_sources.add(src)
                ident_val = item.metadata.get("identifier_value") or item.metadata.get("unusualness")
                if ident_val:
                    matching_idents.append(str(ident_val))

        independent_source_count = max(1, len(independent_sources)) if support_families else 0

        ordered_left, ordered_right = sorted((left_profile_id, right_profile_id))
        return PairAssessment(
            left_profile_id=ordered_left,
            right_profile_id=ordered_right,
            raw_score=raw_score,
            normalized_score=normalized_score,
            classification=classification,
            evidence=all_evidence,
            selected_evidence=selected,
            contributions=contributions,
            support_family_count=len(support_families),
            contradiction_family_count=len(contradiction_families),
            model_version=self.model_version,
            independent_source_count=independent_source_count,
            matching_identifiers=tuple(dict.fromkeys(matching_idents)),
        )

    def contribution(self, item: EvidenceSignal) -> float:
        weight = self.weights.get(item.signal_type, 0.0)
        sign = -1.0 if item.direction is Direction.CONTRADICT else 1.0
        if item.direction is Direction.NEUTRAL:
            sign = 0.0
        return round(sign * weight * item.normalized_score * item.reliability, 6)

    def _select_by_family(
        self,
        evidence: tuple[EvidenceSignal, ...],
    ) -> tuple[EvidenceSignal, ...]:
        grouped: dict[EvidenceFamily, list[EvidenceSignal]] = defaultdict(list)
        for item in evidence:
            if item.direction is not Direction.NEUTRAL:
                grouped[item.evidence_family].append(item)

        selected: list[EvidenceSignal] = []
        for family in sorted(grouped, key=str):
            # Correlated signals (exact hash, pHash, and face similarity, for
            # example) count once. Equal-strength ties prefer contradiction to
            # avoid optimistic identity merges.
            strongest = max(
                grouped[family],
                key=lambda item: (
                    abs(self.contribution(item)),
                    item.direction is Direction.CONTRADICT,
                    item.signal_type.value,
                ),
            )
            selected.append(strongest)
        return tuple(selected)

    def _classify(
        self,
        raw_score: float,
        selected: tuple[EvidenceSignal, ...],
        support_family_count: int,
    ) -> Classification:
        if raw_score <= -10.0:
            return Classification.CONTRADICTORY

        has_anchor = any(
            item.direction is Direction.SUPPORT and item.signal_type in _ANCHOR_SIGNALS
            for item in selected
        )
        has_direct_link = any(
            item.direction is Direction.SUPPORT
            and item.signal_type is SignalType.DIRECT_PROFILE_LINK
            and self.contribution(item) >= 35.0
            for item in selected
        )
        material_contradiction = any(
            item.direction is Direction.CONTRADICT and abs(self.contribution(item)) >= 15.0
            for item in selected
        )

        if (
            raw_score >= 40.0
            and support_family_count >= 2
            and has_anchor
            and not material_contradiction
        ):
            return Classification.STRONG
        if (
            raw_score >= 20.0
            and not material_contradiction
            and (support_family_count >= 2 or has_direct_link)
        ):
            return Classification.LIKELY
        if raw_score >= 7.0:
            return Classification.AMBIGUOUS
        return Classification.WEAK


def score_evidence(
    evidence: Iterable[EvidenceSignal],
    *,
    left_profile_id: str | None = None,
    right_profile_id: str | None = None,
) -> PairAssessment:
    """Score with the default, versioned deterministic model."""

    return CorrelationScorer().score(
        evidence,
        left_profile_id=left_profile_id,
        right_profile_id=right_profile_id,
    )
