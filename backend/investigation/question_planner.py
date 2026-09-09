"""Deterministic selection of one material, low-sensitivity question."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from math import log2

from backend.normalization.profiles import NormalizedProfile


@dataclass(frozen=True, slots=True)
class HypothesisSnapshot:
    id: str
    score: float
    classification: str
    profile_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QuestionPlanOption:
    value: str
    label: str
    hypothesis_id: str | None = None
    profile_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "label": self.label,
            "hypothesis_id": self.hypothesis_id,
            "profile_ids": list(self.profile_ids),
        }


@dataclass(frozen=True, slots=True)
class QuestionPlan:
    question_type: str
    question_text: str
    options: tuple[QuestionPlanOption, ...]
    reason: str
    affected_profile_ids: tuple[str, ...]
    affected_hypothesis_ids: tuple[str, ...]
    expected_information_gain: float
    sensitivity_level: str = "LOW"
    attribute: str = ""


def plan_disambiguation_question(
    hypotheses: tuple[HypothesisSnapshot, ...],
    profiles: Mapping[str, NormalizedProfile],
    *,
    maximum_score_gap: float = 0.40,
) -> QuestionPlan | None:
    """Return one high-value public-attribute question, or no question.

    A question is eligible only when two leading branches are reasonably close
    and each branch has a different observed public attribute. An answer guides
    enrichment; it does not merge identities or change evidence scores.
    """

    ranked = sorted(hypotheses, key=lambda item: (-item.score, item.id))
    if len(ranked) < 2:
        return None
    first, second = ranked[:2]
    if first.score - second.score > maximum_score_gap:
        return None

    for attribute, noun in (
        ("display_name", "display name"),
        ("projects", "public project"),
        ("organization", "organization"),
        ("location", "broad location"),
        ("platform", "platform"),
    ):
        first_value = _consensus_value(first, profiles, attribute)
        second_value = _consensus_value(second, profiles, attribute)
        if not first_value or not second_value or first_value.casefold() == second_value.casefold():
            continue

        choices = (
            QuestionPlanOption(
                value=f"hypothesis:{first.id}",
                label=first_value,
                hypothesis_id=first.id,
                profile_ids=first.profile_ids,
            ),
            QuestionPlanOption(
                value=f"hypothesis:{second.id}",
                label=second_value,
                hypothesis_id=second.id,
                profile_ids=second.profile_ids,
            ),
            QuestionPlanOption(value="neither", label="Neither"),
            QuestionPlanOption(value="skip", label="Not sure / Skip"),
        )
        return QuestionPlan(
            question_type="SINGLE_SELECT",
            question_text=f"Which {noun}, if either, is publicly associated with the person?",
            options=choices,
            reason=(
                f"The two leading candidate branches make different public {noun} claims; "
                "one answer would avoid enriching the less relevant branch."
            ),
            affected_profile_ids=tuple(dict.fromkeys(first.profile_ids + second.profile_ids)),
            affected_hypothesis_ids=(first.id, second.id),
            expected_information_gain=_binary_entropy(first.score, second.score),
            attribute=attribute,
        )
    return None


def _consensus_value(
    hypothesis: HypothesisSnapshot,
    profiles: Mapping[str, NormalizedProfile],
    attribute: str,
) -> str | None:
    values = [
        value
        for profile_id in hypothesis.profile_ids
        if (profile := profiles.get(profile_id)) is not None
        and (value := getattr(profile, attribute, None))
    ]
    if attribute == "projects":
        values = [", ".join(sorted(v)[:3]) for v in values if v]
    if not values:
        return None
    normalized_counts = Counter(value.casefold() for value in values)
    if len(normalized_counts) != 1:
        return None
    normalized, count = normalized_counts.most_common(1)[0]
    if count != len(values):
        return None
    return next(value for value in values if value.casefold() == normalized)


def _binary_entropy(first: float, second: float) -> float:
    total = max(0.0, first) + max(0.0, second)
    if total <= 0:
        return 1.0
    probability = min(0.999999, max(0.000001, max(0.0, first) / total))
    entropy = -(probability * log2(probability)) - ((1.0 - probability) * log2(1.0 - probability))
    return round(entropy, 6)
