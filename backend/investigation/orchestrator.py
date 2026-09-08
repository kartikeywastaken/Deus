"""Bounded application service implementing the deterministic search loop."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from enum import Enum
from typing import Any
from uuid import UUID

from backend.connectors import (
    CandidateProfile,
    ConnectorResult,
    ConnectorRunStatus,
    build_default_registry,
)
from backend.core.config import Settings
from backend.core.enums import SearchStatus, SeedType
from backend.correlation import (
    build_identity_hypotheses,
    generate_candidate_pairs,
    score_evidence,
)
from backend.db.repositories import InvestigationRepository, SearchLimits
from backend.extraction import extract_pair_evidence
from backend.normalization import (
    canonicalize_url,
    normalize_name,
    normalize_profile,
    normalize_username,
)
from backend.reports import (
    ReportEvidence,
    ReportHypothesis,
    ReportProfile,
    build_report,
)

from .pivot_engine import Pivot, PivotEngine, PivotLedger
from .question_planner import HypothesisSnapshot, plan_disambiguation_question
from .target_ranking import rank_hypotheses_for_seed
from .username_questions import (
    DISCOVERY_KINDS,
    question_spec,
    relevance_for_profile,
    user_hint_usernames,
    variants_from_answer,
)


class SearchOrchestrator:
    """Coordinates connectors while deterministic functions retain scoring authority."""

    def __init__(
        self,
        repository: InvestigationRepository,
        settings: Settings,
        *,
        registry: Any | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.registry = registry or build_default_registry(
            mock_connectors=settings.mock_connectors,
            github_token=settings.github_token.get_secret_value()
            if settings.github_token
            else None,
        )
        self.pivots = PivotEngine(self.registry)
        self._connector_semaphore = asyncio.Semaphore(settings.connector_concurrency)

    async def create_and_run(
        self,
        seed_type: SeedType,
        value: str,
        *,
        scope: str = "self_audit",
    ) -> Any:
        normalized_value = _normalize_seed(seed_type, value)
        search = await self.repository.create_search(
            seed_type,
            value,
            normalized_value,
            scope=scope,
            limits=SearchLimits(
                max_pivot_depth=self.settings.max_pivot_depth,
                max_questions=self.settings.max_questions,
                max_connector_runs=self.settings.max_connector_runs,
                max_candidates=self.settings.max_candidates,
                max_search_duration_seconds=self.settings.max_search_duration_seconds,
            ),
        )
        try:
            async with asyncio.timeout(self.settings.max_search_duration_seconds):
                await self._initial_search(search.id, seed_type, normalized_value)
        except TimeoutError:
            await self.repository.update_search(
                search.id,
                status=SearchStatus.FAILED,
                error_summary="The configured search duration limit was reached.",
            )
        except Exception as exc:
            await self.repository.update_search(
                search.id,
                status=SearchStatus.FAILED,
                error_summary=f"{type(exc).__name__}: {exc}",
            )
            raise
        return await self.repository.get_search(search.id)

    async def answer_question(
        self,
        search_id: UUID | str,
        question_id: UUID | str,
        value: str,
    ) -> Any:
        question = await self.repository.get_question(question_id)
        if question is None or str(question.search_run_id) != str(search_id):
            raise LookupError("question not found for this search")
        search = await self._require_search(search_id)
        if _enum_value(question.status) != "PENDING":
            raise ValueError("This question has already been answered.")
        if search.status != SearchStatus.AWAITING_USER:
            raise ValueError("This search is not waiting for an answer.")
        if (getattr(question, "context", {}) or {}).get("kind") in DISCOVERY_KINDS:
            async with asyncio.timeout(self.settings.max_search_duration_seconds):
                return await self._answer_discovery_question(search, question, value)
        option = next(
            (item for item in question.options if str(item.get("value")) == value),
            None,
        )
        if option is None:
            raise ValueError("answer must be one of the question options")

        skipped = value == "skip"
        selected_hypothesis_id = option.get("hypothesis_id")
        await self.repository.answer_question(
            question.id,
            {
                "value": value,
                "label": option.get("label"),
                "selected_hypothesis_id": selected_hypothesis_id,
                "profile_ids": option.get("profile_ids", []),
                "effect": "no score change" if skipped else "branch scores recalculated",
            },
            skipped=skipped,
        )
        search = await self.repository.update_search(
            search_id,
            status=SearchStatus.CONTINUING,
        )

        snapshots = await self.repository.list_profile_snapshots_for_search(search_id)
        selected_profile_ids = set(str(item) for item in option.get("profile_ids", []))
        if not selected_profile_ids:
            selected_profile_ids = {str(item.id) for item in snapshots}
        candidates = [
            _candidate_from_snapshot(item)
            for item in snapshots
            if str(item.id) in selected_profile_ids
        ]
        ledgers = PivotLedger(
            {
                _run_fingerprint(item)
                for item in await self.repository.list_connector_runs(search_id)
            }
        )
        if search.pivot_depth < search.max_pivot_depth:
            gitfive = tuple(
                pivot
                for pivot in self.pivots.enrichment(candidates)
                if pivot.connector_name == "gitfive"
            )
            await self.repository.update_search(
                search_id,
                status=SearchStatus.ENRICHING,
                pivot_depth=search.pivot_depth + 1,
            )
            await self._execute_pivots(search_id, gitfive, ledgers)
        await self._correlate(
            search_id,
            seed_type=search.seeds[0].seed_type,
            seed_value=search.seeds[0].normalized_value or "",
        )
        await self.repository.apply_branch_selection(
            search_id,
            selected_hypothesis_id,
            skipped=skipped,
        )
        await self._finalize(search_id)
        return await self.repository.get_search(search_id)

    async def _answer_discovery_question(self, search, question, value):
        context = question.context
        value = value.strip()
        variants = variants_from_answer(context["kind"], context["base_username"], value)
        await self.repository.answer_question(
            question.id,
            {
                "value": value,
                "label": value,
                "generated_usernames": list(variants),
                "source": "USER_PROVIDED_SEARCH_HINT",
                "question_kind": context["kind"],
                "effect": f"live lookups for {', '.join(variants)}"
                if variants
                else "no identity score change",
            },
            skipped=value == "skip",
        )
        await self.repository.update_search(search.id, status=SearchStatus.CONTINUING)
        if value != "skip" and context["kind"] == "username_numbers":
            kind = "username_digits" if value == "yes" else "username_alias"
            if await self._create_discovery_question(search.id, kind, context["base_username"]):
                return await self.repository.get_search(search.id)
        if variants:
            ledger = PivotLedger(
                {
                    _run_fingerprint(run)
                    for run in await self.repository.list_connector_runs(search.id)
                }
            )
            for username in variants:
                await self._live_search_round(search.id, username, ledger, broad=False)
            await self._correlate(
                search.id,
                seed_type=search.seeds[0].seed_type,
                seed_value=search.seeds[0].normalized_value or "",
            )
        await self._finalize(search.id)
        return await self.repository.get_search(search.id)

    async def _create_discovery_question(self, search_id, kind, base):
        search = await self._require_search(search_id)
        if (
            search.questions_asked >= search.max_questions
            or search.connector_runs_count >= search.max_connector_runs
            or search.pivot_depth >= search.max_pivot_depth
        ):
            return False
        await self.repository.create_question(search_id, **question_spec(kind, base))
        await self.repository.update_search(search_id, status=SearchStatus.AWAITING_USER)
        return True

    async def _live_search_round(self, search_id, username, ledger, *, broad):
        search = await self._require_search(search_id)
        if not broad and search.pivot_depth >= search.max_pivot_depth:
            return
        await self.repository.update_search(search_id, status=SearchStatus.DISCOVERING)
        discovery = self.pivots.discovery(SeedType.USERNAME, username)
        if not broad:
            discovery = tuple(p for p in discovery if p.connector_name != "github_search")
        await self._execute_pivots(search_id, discovery, ledger)
        # Enrich only the searched username, not every vaguely matching search result.
        snapshots = await self.repository.list_profile_snapshots_for_search(search_id)
        selected = [
            _candidate_from_snapshot(item)
            for item in snapshots
            if normalize_username(item.username) == normalize_username(username)
        ]
        enrichment = tuple(
            p for p in self.pivots.enrichment(selected) if p.connector_name == "social_analyzer"
        )[:3]
        await self.repository.update_search(search_id, status=SearchStatus.ENRICHING)
        await self._execute_pivots(search_id, enrichment, ledger)
        if not broad:
            await self.repository.update_search(search_id, pivot_depth=search.pivot_depth + 1)

    async def continue_search(self, search_id: UUID | str) -> Any:
        search = await self._require_search(search_id)
        if search.status in {
            SearchStatus.COMPLETED,
            SearchStatus.CANCELLED,
            SearchStatus.FAILED,
        }:
            return search
        pending = await self.repository.get_pending_question(search_id)
        if pending is not None:
            return await self.answer_question(search_id, pending.id, "skip")
        await self._finalize(search_id)
        return await self.repository.get_search(search_id)

    async def stop_search(self, search_id: UUID | str) -> Any:
        search = await self._require_search(search_id)
        if search.status in {SearchStatus.COMPLETED, SearchStatus.CANCELLED}:
            return search
        pending = await self.repository.get_pending_question(search_id)
        if pending is not None:
            await self.repository.answer_question(
                pending.id,
                {"value": "skip", "effect": "search stopped; no score change"},
                skipped=True,
            )
        await self._finalize(search_id, terminal_status=SearchStatus.CANCELLED)
        return await self.repository.get_search(search_id)

    async def _initial_search(
        self,
        search_id: UUID,
        seed_type: SeedType,
        seed_value: str,
    ) -> None:
        ledger = PivotLedger()
        if not self.settings.mock_connectors and seed_type is SeedType.USERNAME:
            await self._live_search_round(search_id, seed_value, ledger, broad=True)
            await self._correlate(search_id, seed_type=seed_type, seed_value=seed_value)
            if await self._ask_if_useful(search_id):
                return
            await self._finalize(search_id)
            return
        await self.repository.update_search(search_id, status=SearchStatus.DISCOVERING)
        await self._execute_pivots(
            search_id,
            self.pivots.discovery(seed_type, seed_value),
            ledger,
        )

        await self.repository.update_search(search_id, status=SearchStatus.NORMALIZING)
        snapshots = await self.repository.list_profile_snapshots_for_search(search_id)
        usernames = [item.username for item in snapshots if item.username]

        search = await self._require_search(search_id)
        if search.max_pivot_depth >= 1:
            await self.repository.update_search(
                search_id,
                status=SearchStatus.EXPANDING,
                pivot_depth=1,
            )
            await self._execute_pivots(
                search_id,
                self.pivots.expansion(usernames),
                ledger,
            )

            snapshots = await self.repository.list_profile_snapshots_for_search(search_id)
            candidates = [_candidate_from_snapshot(item) for item in snapshots]
            social_pivots = tuple(
                pivot
                for pivot in self.pivots.enrichment(candidates)
                if pivot.connector_name == "social_analyzer"
            )
            await self.repository.update_search(search_id, status=SearchStatus.ENRICHING)
            await self._execute_pivots(search_id, social_pivots, ledger)

        await self._correlate(search_id, seed_type=seed_type, seed_value=seed_value)
        if await self._ask_if_useful(search_id):
            return

        # No useful question exists; finish conditional GitHub enrichment now.
        search = await self._require_search(search_id)
        if search.pivot_depth < search.max_pivot_depth:
            snapshots = await self.repository.list_profile_snapshots_for_search(search_id)
            gitfive = tuple(
                pivot
                for pivot in self.pivots.enrichment(
                    [_candidate_from_snapshot(item) for item in snapshots]
                )
                if pivot.connector_name == "gitfive"
            )
            await self.repository.update_search(
                search_id,
                status=SearchStatus.ENRICHING,
                pivot_depth=search.pivot_depth + 1,
            )
            await self._execute_pivots(search_id, gitfive, ledger)
            await self._correlate(search_id, seed_type=seed_type, seed_value=seed_value)
        await self._finalize(search_id)

    async def _execute_pivots(
        self,
        search_id: UUID | str,
        proposed: tuple[Pivot, ...],
        ledger: PivotLedger,
    ) -> tuple[ConnectorResult, ...]:
        search = await self._require_search(search_id)
        remaining = search.max_connector_runs - search.connector_runs_count
        pivots = self.pivots.claim_within_limit(proposed, ledger, remaining)
        if not pivots:
            return ()

        reservations: list[tuple[Pivot, Any]] = []
        for pivot in pivots:
            run = await self.repository.create_connector_run(
                search_id,
                pivot.connector_name,
                connector_version=self.registry.get(pivot.connector_name).version,
                input_data=pivot.connector_input.model_dump(mode="json"),
                metadata={"stage": pivot.stage, "fingerprint": pivot.fingerprint},
            )
            reservations.append((pivot, run))

        results = await asyncio.gather(
            *(self._invoke_connector(pivot) for pivot, _ in reservations)
        )
        seen_urls = {
            item.canonical_url for item in await self.repository.list_profiles_for_search(search_id)
        }
        for (_pivot, run), result in zip(reservations, results, strict=True):
            result = _trim_candidates(result, seen_urls, search.max_candidates)
            await self.repository.persist_connector_result(run.id, result)
        return tuple(results)

    async def _invoke_connector(self, pivot: Pivot) -> ConnectorResult:
        connector = self.registry.get(pivot.connector_name)
        try:
            async with self._connector_semaphore:
                return await asyncio.wait_for(
                    connector.discover(pivot.connector_input),
                    timeout=self.settings.connector_timeout_seconds,
                )
        except TimeoutError:
            return ConnectorResult(
                connector=connector.name,
                connector_version=connector.version,
                status=ConnectorRunStatus.FAILED,
                message="Connector execution exceeded its configured timeout.",
            )
        except Exception as exc:
            return ConnectorResult(
                connector=connector.name,
                connector_version=connector.version,
                status=ConnectorRunStatus.FAILED,
                message=f"{type(exc).__name__}: {exc}",
            )

    async def _correlate(
        self,
        search_id: UUID | str,
        *,
        seed_type: SeedType,
        seed_value: str,
    ) -> None:
        await self.repository.update_search(search_id, status=SearchStatus.CORRELATING)
        snapshots = await self.repository.list_profile_snapshots_for_search(search_id)
        normalized = tuple(normalize_profile(item) for item in snapshots)
        assessments = []
        for pair in generate_candidate_pairs(normalized):
            evidence = extract_pair_evidence(pair.left, pair.right)
            assessments.append(
                score_evidence(
                    evidence,
                    left_profile_id=pair.left.profile_id,
                    right_profile_id=pair.right.profile_id,
                )
            )
        await self.repository.replace_pair_assessments(search_id, assessments)
        hypotheses = build_identity_hypotheses(normalized, assessments)
        if self.settings.mock_connectors:
            hypotheses = rank_hypotheses_for_seed(
                hypotheses,
                normalized,
                seed_type=SeedType(_enum_value(seed_type)),
                seed_value=seed_value,
            )
        await self.repository.replace_hypotheses(search_id, hypotheses)

    async def _ask_if_useful(self, search_id: UUID | str) -> bool:
        search = await self._require_search(search_id)
        if search.questions_asked >= search.max_questions:
            return False
        hypotheses = await self.repository.list_hypotheses(search_id)
        if not self.settings.mock_connectors:
            # New questions expand collection; an answer never secretly boosts identity scores.
            history = await self.repository.list_questions(search_id)
            seed = search.seeds[0]
            if seed.seed_type == SeedType.USERNAME and not history:
                kind = "username_numbers" if search.max_questions >= 2 else "username_digits"
                return await self._create_discovery_question(
                    search_id, kind, seed.normalized_value or seed.original_value
                )
            return False
        snapshots = await self.repository.list_profile_snapshots_for_search(search_id)
        profiles = {str(item.id): normalize_profile(item) for item in snapshots}
        plan = plan_disambiguation_question(
            tuple(
                HypothesisSnapshot(
                    id=str(item.id),
                    score=item.overall_score,
                    classification=_enum_value(item.classification),
                    profile_ids=tuple(str(member.profile_id) for member in item.memberships),
                )
                for item in hypotheses
            ),
            profiles,
        )
        if plan is None:
            return False
        await self.repository.create_question(
            search_id,
            question_type=plan.question_type,
            question_text=plan.question_text,
            options=[item.as_dict() for item in plan.options],
            reason=plan.reason,
            affected_profile_ids=plan.affected_profile_ids,
            affected_hypothesis_ids=plan.affected_hypothesis_ids,
            expected_information_gain=plan.expected_information_gain,
            sensitivity_level=plan.sensitivity_level,
        )
        await self.repository.update_search(search_id, status=SearchStatus.AWAITING_USER)
        return True

    async def _finalize(
        self,
        search_id: UUID | str,
        *,
        terminal_status: SearchStatus = SearchStatus.COMPLETED,
    ) -> None:
        await self.repository.update_search(search_id, status=SearchStatus.REPORTING)
        hypotheses = await self.repository.list_hypotheses(search_id)
        evidence = await self.repository.list_evidence(search_id)
        observations = await self.repository.list_observations_for_search(search_id)
        questions = await self.repository.list_questions(search_id)
        connector_runs = await self.repository.list_connector_runs(search_id)

        report_hypotheses = []
        for hypothesis in hypotheses:
            profiles = [
                ReportProfile(
                    id=membership.profile.id,
                    platform=membership.profile.platform,
                    username=membership.profile.username,
                    display_name=membership.profile.display_name,
                    canonical_url=membership.profile.canonical_url,
                    score=membership.score,
                    classification=_enum_value(membership.classification),
                )
                for membership in hypothesis.memberships
            ]
            report_hypotheses.append(
                ReportHypothesis(
                    id=hypothesis.id,
                    rank=hypothesis.rank,
                    score=hypothesis.overall_score,
                    classification=_enum_value(hypothesis.classification),
                    profiles=profiles,
                )
            )

        observation_by_id = {item.id: item for item in observations}
        report_evidence = [
            ReportEvidence(
                signal_type=item.signal_type,
                direction=_enum_value(item.direction),
                explanation=item.explanation,
                normalized_score=item.normalized_score,
                reliability=item.reliability,
                source_urls=list(
                    dict.fromkeys(
                        observation_by_id[source_id].source_url
                        for source_id in item.source_observation_ids
                        if source_id in observation_by_id
                        and observation_by_id[source_id].source_url
                    )
                ),
            )
            for item in evidence
        ]
        question_data, answer_impact = _question_history(questions)
        unavailable = [
            item.connector
            for item in connector_runs
            if _enum_value(item.status) in {"DISABLED", "UNAVAILABLE", "AUTH_REQUIRED"}
        ]
        provenance = [
            {
                "observation_id": str(item.id),
                "profile_id": str(item.profile_id),
                "connector": item.connector,
                "source_url": item.source_url,
            }
            for item in observations
        ]
        report = build_report(
            search_run_id=UUID(str(search_id)),
            hypotheses=report_hypotheses,
            evidence=report_evidence,
            questions_asked=question_data,
            unavailable_connectors=unavailable,
            source_provenance=provenance,
            answer_impact=answer_impact,
            connector_runs=[
                {
                    "connector": item.connector,
                    "status": _enum_value(item.status),
                    "error": item.error or item.metadata_json.get("message"),
                    "version": item.connector_version,
                }
                for item in connector_runs
            ],
        )
        search = await self._require_search(search_id)
        hinted = user_hint_usernames(questions)
        snapshots = await self.repository.list_profile_snapshots_for_search(search_id)
        leads = [
            {
                "id": str(item.id),
                "platform": item.platform,
                "username": item.username,
                "canonical_url": item.canonical_url,
                **relevance_for_profile(
                    item.username, search.seeds[0].normalized_value or "", hinted
                ),
            }
            for item in snapshots
        ]
        leads.sort(key=lambda item: (item["priority"], item["platform"], item["username"] or ""))
        report.lead_candidates = leads
        matching = [item for item in leads if item["relevance"] == "USER_HINT_MATCH"]
        if matching:
            names = ", ".join(dict.fromkeys(item["username"] for item in matching))
            report.executive_finding = (
                f"Public accounts matching your username clue were found: {names}. "
                "These are leading search results, not independently verified identities."
            )
        elif hinted:
            report.limitations.append(
                "No collected account matched the username variants from "
                "your answer. Failed checks do not prove absence."
            )
        await self.repository.create_report(search_id, report.model_dump(mode="json"))
        await self.repository.update_search(search_id, status=terminal_status)

    async def _require_search(self, search_id: UUID | str) -> Any:
        search = await self.repository.get_search(search_id)
        if search is None:
            raise LookupError("search not found")
        return search


def _candidate_from_snapshot(snapshot: Any) -> CandidateProfile:
    return CandidateProfile(
        platform=snapshot.platform,
        canonical_url=snapshot.canonical_url,
        platform_account_id=snapshot.platform_account_id,
        username=snapshot.username,
        display_name=snapshot.display_name,
        bio=snapshot.bio,
        location=snapshot.location,
        employer=snapshot.organization,
        external_links=list(snapshot.external_links),
        avatar_url=snapshot.avatar_url,
        discovered_by=list(snapshot.discovered_by),
    )


def _normalize_seed(seed_type: SeedType, value: str) -> str:
    if seed_type is SeedType.USERNAME:
        return normalize_username(value)
    if seed_type is SeedType.NAME:
        return normalize_name(value)
    if seed_type is SeedType.PROFILE_URL:
        return canonicalize_url(value)
    if seed_type is SeedType.EMAIL:
        return value.strip().casefold()
    return value.strip()


def _trim_candidates(
    result: ConnectorResult,
    seen_urls: set[str],
    maximum: int,
) -> ConnectorResult:
    accepted: list[CandidateProfile] = []
    for profile in result.profiles:
        canonical = canonicalize_url(profile.canonical_url)
        if canonical in seen_urls or len(seen_urls) < maximum:
            accepted.append(profile)
            seen_urls.add(canonical)
    if len(accepted) == len(result.profiles):
        return result
    return result.model_copy(
        update={
            "profiles": accepted,
            "metadata": {**result.metadata, "candidate_limit_applied": True},
        }
    )


def _question_history(questions: Iterable[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    history: list[dict[str, Any]] = []
    impacts: list[str] = []
    for question in questions:
        answer = question.answers[-1].answer if question.answers else None
        history.append(
            {
                "question": question.question_text,
                "reason": question.reason,
                "answer": answer,
                "status": _enum_value(question.status),
            }
        )
        if answer:
            label = answer.get("label") or answer.get("value")
            effect = answer.get("effect", "branch scores recalculated")
            impacts.append(f"Answer '{label}' caused {effect}.")
    return history, impacts


def _run_fingerprint(run: Any) -> str:
    metadata = run.metadata_json or {}
    if metadata.get("fingerprint"):
        return str(metadata["fingerprint"])
    input_type = (run.input_data or {}).get("type", "UNKNOWN")
    value = (run.input_data or {}).get("value", "")
    return f"{run.connector.casefold()}:{input_type}:{str(value).casefold()}"


def _enum_value(value: Any) -> str:
    return str(value.value) if isinstance(value, Enum) else str(value)
