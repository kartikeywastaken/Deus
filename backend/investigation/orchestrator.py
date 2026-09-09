"""One live, resumable investigation workflow shared by API jobs and CLI."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from enum import Enum
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from backend.connectors import (
    CandidateProfile,
    ConnectorInput,
    ConnectorInputType,
    ConnectorResult,
    ConnectorRunStatus,
    build_default_registry,
)
from backend.connectors.profile_links import declared_profiles, profile_link
from backend.connectors.social_live import site_for_url
from backend.core.config import Settings
from backend.core.enums import SearchStatus, SeedType
from backend.correlation import build_identity_hypotheses, generate_candidate_pairs, score_evidence
from backend.correlation.engine import candidate_relevance
from backend.db.repositories import InvestigationRepository
from backend.extraction import extract_pair_evidence
from backend.normalization import (
    canonicalize_url,
    normalize_name,
    normalize_profile,
    normalize_username,
)
from backend.reports import ReportEvidence, ReportHypothesis, ReportProfile, build_report

from .pivot_engine import Pivot, PivotEngine, PivotLedger
from .planner import Action, choose_action
from .question_planner import HypothesisSnapshot, plan_disambiguation_question
from .username_questions import question_spec, relevance_for_profile, user_hint_usernames


class SearchOrchestrator:
    def __init__(
        self,
        repository: InvestigationRepository,
        settings: Settings,
        *,
        registry=None,
        checkpoint=None,
    ):
        self.repository = repository
        self.settings = settings
        self.registry = registry or build_default_registry(
            github_token=settings.github_token.get_secret_value() if settings.github_token else None
        )
        self.pivots = PivotEngine(self.registry)
        self._connector_semaphore = asyncio.Semaphore(settings.connector_concurrency)
        self._checkpoint_callback = checkpoint

    async def checkpoint(self):
        if self._checkpoint_callback:
            await self._checkpoint_callback()

    async def run_search(self, search_id):
        """Reconstruct work from persisted observations, runs and answers after any restart."""
        for _ in range(self.settings.max_connector_runs + self.settings.max_questions + 5):
            await self.checkpoint()
            search = await self._require_search(search_id)
            if search.status in {
                SearchStatus.CANCELLED,
                SearchStatus.COMPLETED,
                SearchStatus.FAILED,
            }:
                return search
            if await self.repository.get_pending_question(search_id):
                await self.repository.update_search(search_id, status=SearchStatus.AWAITING_USER)
                await self.checkpoint()
                return search
            seed = search.seeds[0]
            runs = await self.repository.list_connector_runs(search_id)
            ledger = PivotLedger({_run_fingerprint(run) for run in runs})
            questions = await self.repository.list_questions(search_id)
            profiles = await self.repository.list_profile_snapshots_for_search(search_id)
            hypotheses = await self.repository.list_hypotheses(search_id)
            initial = self.pivots.discovery(
                seed.seed_type, seed.normalized_value or seed.original_value
            )
            initial = tuple(p for p in initial if ledger.unseen(p))
            hinted = user_hint_usernames(questions)
            name_handles = (
                tuple(
                    dict.fromkeys(
                        p.username for p in profiles if p.username and p.platform == "github"
                    )
                )[:3]
                if seed.seed_type == SeedType.NAME
                else ()
            )
            hint_pivots = tuple(
                p
                for username in sorted(hinted) or name_handles
                for p in self.pivots.discovery(SeedType.USERNAME, username)
                if p.connector_name != "github_search" and ledger.unseen(p)
            )
            next_question = None
            base = seed.normalized_value or seed.original_value
            if not questions and seed.seed_type == SeedType.USERNAME:
                numeric_variants = [
                    p
                    for p in profiles
                    if p.username
                    and p.username.casefold() != base.casefold()
                    and any(c.isdigit() for c in p.username)
                ]
                # Observed variants or weak matches leave useful discovery uncertainty.
                if (
                    numeric_variants
                    or not hypotheses
                    or max(h.overall_score for h in hypotheses) < 0.45
                ):
                    kind = "username_numbers" if search.max_questions >= 2 else "username_digits"
                    next_question = question_spec(kind, base)
            elif questions:
                latest = questions[-1]
                context = latest.context or {}
                answer = latest.answers[-1].answer if latest.answers else {}
                if context.get("kind") == "username_numbers" and answer.get("value") in {
                    "yes",
                    "no",
                }:
                    next_question = question_spec(
                        "username_digits" if answer["value"] == "yes" else "username_alias", base
                    )
            preferred = [
                p
                for p in profiles
                if normalize_username(p.username)
                in (
                    hinted
                    or {normalize_username(n) for n in name_handles}
                    or {normalize_username(base)}
                )
            ]
            if seed.seed_type == SeedType.PROFILE_URL:
                preferred = [p for p in profiles if p.canonical_url == canonicalize_url(base)]
            # Follow observed outgoing links even when the next handle differs.
            # This is bounded by persisted run/depth/candidate/time budgets.
            reachable = {p.canonical_url for p in preferred}
            for _ in range(search.max_pivot_depth + 1):
                reachable.update(
                    link
                    for p in profiles
                    if p.canonical_url in reachable
                    for link in p.external_links
                )
            preferred.extend(
                p for p in profiles if p.canonical_url in reachable and p not in preferred
            )
            platform_questions = [
                q for q in questions if q.context.get("kind") == "platform_priority"
            ]
            platforms = sorted({p.platform for p in preferred} - {"githubgist"})
            if hinted and not hint_pivots and not platform_questions and len(platforms) > 1:
                next_question = {
                    "question_type": "MULTI_SELECT",
                    "question_text": "Which discovered platforms should I prioritize?",
                    "options": [{"value": p, "label": p} for p in platforms]
                    + [{"value": "skip", "label": "No preference / continue"}],
                    "context": {"kind": "platform_priority"},
                    "reason": "Choose where to spend the remaining collection budget; "
                    "this does not confirm account ownership.",
                    "sensitivity_level": "LOW",
                    "expected_information_gain": None,
                }
            if platform_questions and platform_questions[-1].answers:
                selected = platform_questions[-1].answers[-1].answer.get("value")
                if isinstance(selected, list):
                    preferred.sort(key=lambda p: p.platform not in selected)
            branch_questions = [q for q in questions if q.context.get("kind") == "attribute_branch"]
            if branch_questions and branch_questions[-1].answers:
                chosen_ids = branch_questions[-1].answers[-1].answer.get("selected_profile_ids", [])
                if chosen_ids:
                    preferred = sorted(profiles, key=lambda p: str(p.id) not in chosen_ids)[:3]
            if not next_question and not branch_questions and len(profiles) > 1:
                plan = plan_disambiguation_question(
                    tuple(
                        HypothesisSnapshot(
                            str(h.id),
                            h.overall_score,
                            h.classification.value,
                            tuple(str(m.profile_id) for m in h.memberships),
                        )
                        for h in hypotheses
                    ),
                    {str(p.id): normalize_profile(p) for p in profiles},
                )
                if plan:
                    next_question = {
                        "question_type": plan.question_type,
                        "question_text": plan.question_text,
                        "options": [o.as_dict() for o in plan.options],
                        "reason": plan.reason,
                        "affected_profile_ids": plan.affected_profile_ids,
                        "affected_hypothesis_ids": plan.affected_hypothesis_ids,
                        "expected_information_gain": plan.expected_information_gain,
                        "context": {"kind": "attribute_branch", "attribute": plan.attribute},
                    }
            enrichment = []
            for p in sorted(
                preferred, key=lambda p: (not p.external_links, p.platform != "github")
            ):
                if (
                    p.platform == "github"
                    and search.scope == "self_audit"
                    and self.settings.gitfive_enabled
                ):
                    enrichment.append(
                        Pivot(
                            "gitfive",
                            ConnectorInput(
                                type=ConnectorInputType.GITHUB_PROFILE, value=p.canonical_url
                            ),
                            "ENRICHING",
                            35,
                        )
                    )
                for link in p.external_links[:10]:
                    host = urlsplit(link).hostname
                    if host == "github.com":
                        enrichment.append(
                            Pivot(
                                "github",
                                ConnectorInput(type=ConnectorInputType.PROFILE_URL, value=link),
                                "ENRICHING",
                                30,
                            )
                        )
                    elif host:
                        enrichment.append(
                            Pivot(
                                "website",
                                ConnectorInput(type=ConnectorInputType.PROFILE_URL, value=link),
                                "ENRICHING",
                                40,
                            )
                        )
                if p.platform == "github":
                    enrichment.append(
                        Pivot(
                            "github",
                            ConnectorInput(
                                type=ConnectorInputType.PROFILE_URL, value=p.canonical_url
                            ),
                            "ENRICHING",
                            30,
                        )
                    )
                else:
                    enrichment.append(
                        Pivot(
                            "website",
                            ConnectorInput(
                                type=ConnectorInputType.PROFILE_URL, value=p.canonical_url
                            ),
                            "ENRICHING",
                            35,
                        )
                    )
                enrichment.extend(
                    pivot
                    for pivot in self.pivots.enrichment([_candidate_from_snapshot(p)])
                    if pivot.connector_name == "social_analyzer" and site_for_url(p.canonical_url)
                )
            # Leave run budget for newly discovered links on subsequent hops.
            preferred_ids = {p.id for p in preferred}
            for observation in await self.repository.list_observations_for_search(search_id):
                data = observation.normalized_data or {}
                if (
                    observation.profile_id in preferred_ids
                    and data.get("signal_type")
                    in {"REPOSITORY_SOCIAL_REFERENCE", "PAGE_SOCIAL_REFERENCE"}
                    and isinstance(data.get("value"), str)
                ):
                    target = profile_link(data["value"])
                    if target:
                        enrichment.append(
                            Pivot(
                                "github" if target[0] == "github" else "website",
                                ConnectorInput(
                                    type=ConnectorInputType.PROFILE_URL, value=target[2]
                                ),
                                "ENRICHING",
                                60,
                            )
                        )
            enrichment = tuple({p.fingerprint: p for p in enrichment if ledger.unseen(p)}.values())[
                :6
            ]
            action = choose_action(
                initial=initial,
                hints=hint_pivots,
                question=next_question,
                enrichment=enrichment,
                runs_remaining=search.max_connector_runs - search.connector_runs_count,
                questions_remaining=search.max_questions - search.questions_asked,
                pivot_remaining=search.max_pivot_depth - search.pivot_depth,
                leading_score=max((h.overall_score for h in hypotheses), default=0),
            )
            from backend.db.models import UserSearchContext

            from .adviser import advise

            action, advice = await advise(action, self.settings)
            self.repository.session.add(
                UserSearchContext(
                    search_run_id=search.id,
                    context_type="PLANNER_DECISION",
                    value={"action": action.kind, "reason": action.reason, "adviser": advice},
                )
            )
            if action.kind in {Action.RUN_CONNECTOR, Action.RUN_PIVOT}:
                await self.repository.update_search(search_id, status=SearchStatus.DISCOVERING)
                await self._execute_pivots(search_id, action.pivots, ledger)
                if action.kind == Action.RUN_PIVOT:
                    await self.repository.update_search(
                        search_id, pivot_depth=search.pivot_depth + 1
                    )
                await self._correlate(search_id, seed_type=seed.seed_type, seed_value=base)
                await self.checkpoint()
            elif action.kind == Action.ASK_QUESTION:
                await self.repository.create_question(search_id, **action.question)
                await self.repository.update_search(search_id, status=SearchStatus.AWAITING_USER)
                await self.checkpoint()
                return await self.repository.get_search(search_id)
            else:
                await self._correlate(search_id, seed_type=seed.seed_type, seed_value=base)
                await self._finalize(search_id)
                await self.checkpoint()
                return await self.repository.get_search(search_id)
        await self._finalize(search_id)
        await self.checkpoint()

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

        await self.checkpoint()
        results = await asyncio.gather(
            *(self._invoke_connector(pivot) for pivot, _ in reservations)
        )
        seen_urls = {
            item.canonical_url for item in await self.repository.list_profiles_for_search(search_id)
        }
        await self.checkpoint()
        for (_pivot, run), result in zip(reservations, results, strict=True):
            result = declared_profiles(result)
            initial_seed = search.seeds[0].normalized_value or search.seeds[0].original_value
            reserve = min(5, search.max_candidates // 4)
            maximum = (
                search.max_candidates - 2 * reserve
                if _pivot.stage == "DISCOVERING"
                and _pivot.connector_input.value.casefold() == initial_seed.casefold()
                else search.max_candidates - reserve
                if _pivot.stage == "DISCOVERING"
                else search.max_candidates
            )
            result = _trim_candidates(result, seen_urls, maximum)
            await self.repository.persist_connector_result(run.id, result)
            await self.checkpoint()
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
        semantic_neighbors = ()
        if self.settings.text_embeddings_enabled:
            from backend.embeddings.service import enrich_bios

            normalized, semantic_neighbors = await enrich_bios(self.repository.session, normalized)
        assessments = []
        for pair in generate_candidate_pairs(normalized, semantic_neighbors=semantic_neighbors):
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
        await self.repository.replace_hypotheses(search_id, hypotheses)

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
        report.self_audit_findings = [
            {
                "connector": r.connector,
                "status": r.status.value,
                "breach_names": r.metadata_json.get("breach_names", []),
                "note": "Separate defensive self-audit; not identity evidence.",
            }
            for r in connector_runs
            if r.connector == "hibp"
        ]
        snapshots = await self.repository.list_profile_snapshots_for_search(search_id)
        from .account_groups import account_details

        report.account_associations = [
            {
                "profile_id": str(p.id),
                "canonical_url": p.canonical_url,
                **account_details(snapshots)[p.id],
            }
            for p in snapshots
        ]
        report.repository_references = [
            {
                "source_url": o.source_url,
                "url": o.normalized_data.get("value"),
                "note": "Public-page/repository reference; not account ownership evidence.",
            }
            for o in observations
            if o.normalized_data.get("signal_type")
            in {"REPOSITORY_SOCIAL_REFERENCE", "PAGE_SOCIAL_REFERENCE"}
        ]
        leads = [
            {
                "id": str(item.id),
                "platform": item.platform,
                "username": item.username,
                "canonical_url": item.canonical_url,
                **candidate_relevance(
                    item.username,
                    search.seeds[0].normalized_value or "",
                    max(
                        (
                            m.score
                            for h in hypotheses
                            for m in h.memberships
                            if m.profile_id == item.id
                        ),
                        default=0.0,
                    ),
                    seed_type=search.seeds[0].seed_type.value,
                    hinted=hinted,
                ),
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
            "status": ConnectorRunStatus.PARTIAL,
            "message": (result.message or "")
            + " Candidate capacity applied; space reserved for later clues.",
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
