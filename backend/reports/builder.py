from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from .schemas import RankedReport, ReportEvidence, ReportHypothesis


def build_report(
    *,
    search_run_id: UUID,
    hypotheses: Iterable[ReportHypothesis],
    evidence: Iterable[ReportEvidence],
    questions_asked: list[dict] | None = None,
    unavailable_connectors: list[str] | None = None,
    source_provenance: list[dict] | None = None,
    answer_impact: list[str] | None = None,
    connector_runs: list[dict] | None = None,
) -> RankedReport:
    """Build a factual report from already-computed hypotheses and evidence.

    This function deliberately does not calculate scores. It only ranks and explains
    deterministic correlation output, keeping report prose separate from identity logic.
    """

    ranked = sorted(hypotheses, key=lambda item: (-item.score, str(item.id)))
    for index, hypothesis in enumerate(ranked, start=1):
        hypothesis.rank = index

    primary = ranked[0] if ranked else None
    evidence_items = list(evidence)
    support = [item for item in evidence_items if item.direction.upper() == "SUPPORT"]
    strong_support = [item for item in support if item.normalized_score * item.reliability >= 0.70]
    moderate_support = [item for item in support if item.normalized_score * item.reliability < 0.70]
    contradictions = [item for item in evidence_items if item.direction.upper() == "CONTRADICT"]

    if primary is None:
        finding = "Insufficient evidence to form an identity hypothesis."
    elif primary.classification.upper() in {"WEAK", "AMBIGUOUS", "CONTRADICTORY"}:
        finding = (
            "Public candidates were found, but evidence is insufficient "
            "to identify a reliable match."
        )
    else:
        finding = (
            f"The highest-scoring candidate cluster is classified {primary.classification.lower()} "
            f"with an uncalibrated evidence score of {primary.score:.3f}."
        )

    limitations = [
        "A discovered public profile is a candidate, not a confirmed identity.",
        "Scores are deterministic evidence scores and are not calibrated probabilities.",
        "Unavailable platforms and private data are not represented in this report.",
        "Matching usernames or repeated tool detections alone do not establish shared identity.",
    ]
    if any(run.get("status") not in {"SUCCESS", "NO_RESULTS"} for run in connector_runs or []):
        limitations.append(
            "Collection is incomplete: review individual connector statuses and errors."
        )

    return RankedReport(
        search_run_id=search_run_id,
        executive_finding=finding,
        primary_hypothesis=primary,
        alternative_hypotheses=ranked[1:],
        supporting_evidence=sorted(
            strong_support,
            key=lambda item: (-(item.normalized_score * item.reliability), item.signal_type),
        ),
        moderate_evidence=sorted(
            moderate_support,
            key=lambda item: (-(item.normalized_score * item.reliability), item.signal_type),
        ),
        contradictions=sorted(
            contradictions,
            key=lambda item: (-(item.normalized_score * item.reliability), item.signal_type),
        ),
        source_provenance=source_provenance or [],
        questions_asked=questions_asked or [],
        answer_impact=answer_impact or [],
        unavailable_connectors=sorted(set(unavailable_connectors or [])),
        connector_runs=connector_runs or [],
        limitations=limitations,
        suggested_next_public_sources=[
            "Review the linked public personal domains and cross-profile links.",
            "Re-run supported public connectors later to check for changed profile claims.",
        ],
    )
