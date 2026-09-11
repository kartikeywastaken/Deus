"""Async PostgreSQL repository for the OSINT investigation lifecycle.

The repository is intentionally transaction-neutral: methods flush their
writes, while the API request or background worker that created the session
decides when to commit or roll back the complete workflow step.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.connectors.schemas import (
    CandidateProfile,
    ConnectorResult,
    IdentifierArtifact,
    IdentifierType,
)
from backend.core.enums import (
    Classification,
    ConnectorStatus,
    EvidenceDirection,
    HypothesisStatus,
    QuestionStatus,
    QuestionType,
    SearchStatus,
    SeedType,
    SensitivityLevel,
)
from backend.correlation.features import (
    EvidenceSignal as DomainEvidenceSignal,
)
from backend.correlation.features import (
    IdentityHypothesis as DomainIdentityHypothesis,
)
from backend.correlation.features import (
    PairAssessment,
)
from backend.db.models import (
    ConnectorRun,
    EvidenceSignal,
    HypothesisMembership,
    Identifier,
    IdentityHypothesis,
    InvestigationAnswer,
    InvestigationQuestion,
    Profile,
    ProfileIdentifier,
    ProfileObservation,
    ProfileRelationship,
    Report,
    SearchRun,
    SearchSeed,
    utc_now,
)
from backend.events import emit
from backend.normalization.domains import is_personal_domain, normalize_domain
from backend.normalization.names import normalize_name
from backend.normalization.urls import canonicalize_url
from backend.normalization.usernames import normalize_username

from .types import (
    GraphEdgeData,
    GraphNodeData,
    GraphSnapshot,
    PersistedConnectorResult,
    ProfileSnapshot,
    QuestionAnswerResult,
    SearchLimits,
)


class RepositoryEntityNotFound(LookupError):
    """Raised when a requested aggregate does not exist."""


class InvalidRepositoryState(RuntimeError):
    """Raised when a write would violate investigation state or identity safety."""


@dataclass(frozen=True, slots=True)
class _IdentifierSpec:
    identifier_type: str
    value: str
    normalized_value: str
    relationship_type: str
    confidence: float
    metadata: Mapping[str, Any]


class PostgresInvestigationRepository:
    """SQLAlchemy 2 async implementation backed specifically by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_search(
        self,
        seed_type: SeedType | str,
        original_value: str,
        normalized_value: str | None = None,
        *,
        scope: str = "self_audit",
        limits: SearchLimits | None = None,
        retention_expires_at: datetime | None = None,
    ) -> SearchRun:
        """Create a bounded investigation and its immutable initial seed."""

        original_value = original_value.strip()
        if not original_value:
            raise ValueError("search seed cannot be blank")
        if scope not in {"self_audit", "consented", "public_figure"}:
            raise ValueError("unsupported investigation scope")

        limits = limits or SearchLimits()
        _validate_limits(limits)
        search = SearchRun(
            scope=scope,
            retention_expires_at=retention_expires_at,
            max_pivot_depth=limits.max_pivot_depth,
            max_questions=limits.max_questions,
            max_connector_runs=limits.max_connector_runs,
            max_candidates=limits.max_candidates,
            max_search_duration_seconds=limits.max_search_duration_seconds,
        )
        seed = SearchSeed(
            seed_type=SeedType(_enum_value(seed_type)),
            original_value=original_value,
            normalized_value=(normalized_value or original_value).strip(),
        )
        search.seeds.append(seed)
        self.session.add(search)
        await self.session.flush()
        emit(self.session, search.id, "CREATED", status="CREATED")
        return search

    async def get_search(self, search_id: UUID | str) -> SearchRun | None:
        """Fetch a search and its seed records without loading large result sets."""

        statement = (
            select(SearchRun)
            .where(SearchRun.id == _as_uuid(search_id, "search_id"))
            .options(selectinload(SearchRun.seeds))
        )
        return await self.session.scalar(statement)

    async def update_search(self, search_id: UUID | str, **fields: Any) -> SearchRun:
        """Update lifecycle state or bounded-work counters on an existing search."""

        allowed = {
            "status",
            "scope",
            "started_at",
            "completed_at",
            "retention_expires_at",
            "pivot_depth",
            "questions_asked",
            "connector_runs_count",
            "max_pivot_depth",
            "max_questions",
            "max_connector_runs",
            "max_candidates",
            "max_search_duration_seconds",
            "error_summary",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unsupported search fields: {', '.join(sorted(unknown))}")
        search = await self.session.scalar(
            select(SearchRun)
            .where(SearchRun.id == _as_uuid(search_id, "search_id"))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if search is None:
            raise RepositoryEntityNotFound("search not found")
        if search.status == SearchStatus.CANCELLED:
            return search
        previous_status = search.status
        if "status" in fields:
            fields["status"] = SearchStatus(_enum_value(fields["status"]))
        for name, value in fields.items():
            setattr(search, name, value)

        if search.status is not SearchStatus.CREATED and search.started_at is None:
            search.started_at = utc_now()
        if (
            search.status
            in {
                SearchStatus.COMPLETED,
                SearchStatus.FAILED,
                SearchStatus.CANCELLED,
            }
            and search.completed_at is None
        ):
            search.completed_at = utc_now()
        await self.session.flush()
        if previous_status != search.status:
            emit(self.session, search.id, search.status.value, status=search.status.value)
        return search

    async def create_connector_run(
        self,
        search_id: UUID | str,
        connector: str,
        *,
        connector_version: str | None = None,
        input_data: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ConnectorRun:
        """Reserve one connector attempt and enforce the search's hard run cap."""

        connector = connector.strip()
        if not connector:
            raise ValueError("connector name cannot be blank")
        search = await self._require_search(search_id)
        if search.connector_runs_count >= search.max_connector_runs:
            raise InvalidRepositoryState("maximum connector-run limit reached")

        search.connector_runs_count += 1
        connector_run = ConnectorRun(
            search_run_id=search.id,
            connector=connector,
            connector_version=connector_version,
            status=ConnectorStatus.RUNNING,
            started_at=utc_now(),
            input_data=_jsonable(input_data or {}),
            metadata_json=_jsonable(metadata or {}),
        )
        self.session.add(connector_run)
        await self.session.flush()
        emit(
            self.session,
            search.id,
            "CONNECTOR_STARTED",
            connector=connector,
            run_id=str(connector_run.id),
        )
        return connector_run

    async def persist_connector_result(
        self,
        connector_run_id: UUID | str,
        result: ConnectorResult,
    ) -> PersistedConnectorResult:
        """Persist profiles, facts, raw output, and provenance for one run."""

        run = await self.session.get(ConnectorRun, _as_uuid(connector_run_id, "connector_run_id"))
        if run is None:
            raise RepositoryEntityNotFound("connector run not found")
        if run.connector.casefold() != result.connector.casefold():
            raise InvalidRepositoryState("connector result does not match reserved run")

        previous_status = run.status
        run.connector_version = result.connector_version
        run.status = ConnectorStatus(result.status.value)
        run.completed_at = utc_now()
        run.request_count = result.request_count
        run.error = result.message if run.status in _ERROR_CONNECTOR_STATUSES else None
        run.metadata_json = {
            **(run.metadata_json or {}),
            **_jsonable(result.metadata),
            "message": result.message,
            "raw_records": _jsonable(result.raw_records),
            "identifier_relationships": _jsonable(result.relationships),
        }

        # A terminal result may be replayed safely to repair materialized data;
        # connector attempt counters were already reserved when the run began.
        if previous_status not in {ConnectorStatus.PENDING, ConnectorStatus.RUNNING}:
            run.metadata_json["replayed_terminal_result"] = True

        candidates = _deduplicate_candidates(result.profiles)
        previous_ids = {p.id for p in await self.list_profiles_for_search(run.search_run_id)}
        profiles: list[Profile] = []
        profiles_by_url: dict[str, Profile] = {}
        observations: list[ProfileObservation] = []

        for candidate in candidates:
            profile = await self._upsert_profile(candidate)
            profiles_by_url[profile.canonical_url] = profile
            if profile not in profiles:
                profiles.append(profile)

        for candidate in candidates:
            canonical_url = canonicalize_url(candidate.canonical_url)
            profile = profiles_by_url[canonical_url]
            observation = await self._add_profile_observation(
                run,
                profile,
                source_url=candidate.source_url or candidate.canonical_url,
                normalized_data=_candidate_normalized_data(candidate),
                raw_data=candidate.raw,
            )
            observations.append(observation)
            for spec in _candidate_identifier_specs(candidate):
                await self._link_identifier(profile, observation, spec)

        for artifact in result.observations:
            profile = await self._resolve_artifact_profile(
                run,
                artifact.profile_url,
                profiles_by_url,
            )
            if profile is None:
                run.metadata_json.setdefault("unresolved_observations", []).append(
                    _jsonable(artifact)
                )
                continue
            if profile not in profiles:
                profiles.append(profile)
            observation = await self._add_profile_observation(
                run,
                profile,
                source_url=artifact.source_url or artifact.profile_url,
                normalized_data={
                    "signal_type": artifact.signal_type,
                    "value": _jsonable(artifact.value),
                    "reliability": artifact.reliability,
                },
                raw_data=artifact.raw_data,
            )
            observations.append(observation)

        for artifact in result.identifiers:
            profile = await self._resolve_identifier_profile(
                run,
                artifact,
                profiles_by_url,
                profiles,
            )
            if profile is None:
                run.metadata_json.setdefault("unresolved_identifiers", []).append(
                    _jsonable(artifact)
                )
                continue
            if profile not in profiles:
                profiles.append(profile)
            observation = await self._add_profile_observation(
                run,
                profile,
                source_url=artifact.source_url or artifact.profile_url,
                normalized_data={
                    "signal_type": "public_identifier",
                    "identifier_type": artifact.type.value,
                    "value": artifact.value,
                    "normalized_value": artifact.normalized_value,
                },
                raw_data=artifact.metadata,
            )
            observations.append(observation)
            await self._link_identifier(
                profile,
                observation,
                _IdentifierSpec(
                    identifier_type=artifact.type.value,
                    value=artifact.value,
                    normalized_value=artifact.normalized_value,
                    relationship_type="CONNECTOR_ARTIFACT",
                    confidence=1.0,
                    metadata=artifact.metadata,
                ),
            )

        await self._persist_cross_profile_links(run, candidates, profiles_by_url)
        await self._persist_resolved_relationships(run, result, profiles)
        await self.session.flush()
        for profile in profiles:
            if profile.id not in previous_ids:
                emit(
                    self.session,
                    run.search_run_id,
                    "CANDIDATE_DISCOVERED",
                    profile_id=str(profile.id),
                    platform=profile.platform,
                )
        emit(
            self.session,
            run.search_run_id,
            "CONNECTOR_COMPLETED",
            connector=run.connector,
            run_id=str(run.id),
            status=run.status.value,
            candidates=len(profiles),
        )
        return PersistedConnectorResult(run, tuple(profiles), tuple(observations))

    async def list_connector_runs(self, search_id: UUID | str) -> list[ConnectorRun]:
        statement = (
            select(ConnectorRun)
            .where(ConnectorRun.search_run_id == _as_uuid(search_id, "search_id"))
            .order_by(ConnectorRun.started_at, ConnectorRun.id)
        )
        return list((await self.session.scalars(statement)).all())

    async def list_profiles_for_search(self, search_id: UUID | str) -> list[Profile]:
        """List globally deduplicated profiles observed in this search."""

        search_uuid = _as_uuid(search_id, "search_id")
        observed = exists(
            select(ProfileObservation.id).where(
                ProfileObservation.search_run_id == search_uuid,
                ProfileObservation.profile_id == Profile.id,
            )
        )
        statement = select(Profile).where(observed).order_by(Profile.platform, Profile.id)
        return list((await self.session.scalars(statement)).all())

    async def list_observations_for_search(self, search_id: UUID | str) -> list[ProfileObservation]:
        statement = (
            select(ProfileObservation)
            .where(ProfileObservation.search_run_id == _as_uuid(search_id, "search_id"))
            .order_by(ProfileObservation.observed_at, ProfileObservation.id)
        )
        return list((await self.session.scalars(statement)).all())

    async def list_profile_snapshots_for_search(
        self, search_id: UUID | str
    ) -> list[ProfileSnapshot]:
        """Return correlation-ready detached profiles with observation facts folded in."""

        profiles = await self.list_profiles_for_search(search_id)
        observations = await self.list_observations_for_search(search_id)
        by_profile: dict[UUID, list[ProfileObservation]] = {}
        for observation in observations:
            by_profile.setdefault(observation.profile_id, []).append(observation)
        return [
            _build_profile_snapshot(profile, by_profile.get(profile.id, [])) for profile in profiles
        ]

    async def replace_evidence(
        self,
        search_id: UUID | str,
        signals: Iterable[DomainEvidenceSignal],
        *,
        contribution_by_key: Mapping[Any, float] | None = None,
        extractor_version: str = "deterministic-v0.1",
    ) -> list[EvidenceSignal]:
        """Replace the complete deterministic evidence set for one search."""

        search_uuid = _as_uuid(search_id, "search_id")
        await self._require_search(search_uuid)
        await self.session.execute(
            delete(EvidenceSignal).where(EvidenceSignal.search_run_id == search_uuid)
        )
        contributions = contribution_by_key or {}
        stored: list[EvidenceSignal] = []
        for signal in signals:
            left_id, right_id = (_as_uuid(item, "profile_id") for item in signal.pair_key)
            key = evidence_key(signal)
            source_ids = [
                _as_uuid(item, "source_observation_id") for item in signal.source_observation_ids
            ]
            raw_value = dict(signal.metadata)
            if signal.source_key is not None:
                raw_value["source_key"] = signal.source_key
            row = EvidenceSignal(
                search_run_id=search_uuid,
                left_profile_id=left_id,
                right_profile_id=right_id,
                signal_type=signal.signal_type.value,
                direction=EvidenceDirection(signal.direction.value),
                raw_value=_jsonable(raw_value),
                normalized_score=signal.normalized_score,
                reliability=signal.reliability,
                model_contribution=_lookup_contribution(contributions, signal, key),
                evidence_family=signal.evidence_family.value,
                source_observation_ids=source_ids,
                extractor_version=extractor_version,
                explanation=signal.explanation,
            )
            self.session.add(row)
            stored.append(row)
        await self.session.flush()
        return stored

    async def replace_pair_assessments(
        self,
        search_id: UUID | str,
        assessments: Iterable[PairAssessment],
    ) -> list[EvidenceSignal]:
        """Convenience adapter that persists evidence and selected contributions."""

        assessment_items = tuple(assessments)
        signals: list[DomainEvidenceSignal] = []
        contributions: dict[Any, float] = {}
        model_versions = {item.model_version for item in assessment_items}
        for assessment in assessment_items:
            signals.extend(assessment.evidence)
            for contribution in assessment.contributions:
                contributions[evidence_key(contribution.evidence)] = contribution.weighted_score
        extractor_version = (
            next(iter(model_versions)) if len(model_versions) == 1 else "deterministic-v0.1"
        )
        return await self.replace_evidence(
            search_id,
            signals,
            contribution_by_key=contributions,
            extractor_version=extractor_version,
        )

    async def list_evidence(self, search_id: UUID | str) -> list[EvidenceSignal]:
        statement = (
            select(EvidenceSignal)
            .where(EvidenceSignal.search_run_id == _as_uuid(search_id, "search_id"))
            .order_by(
                EvidenceSignal.left_profile_id,
                EvidenceSignal.right_profile_id,
                EvidenceSignal.signal_type,
                EvidenceSignal.id,
            )
        )
        return list((await self.session.scalars(statement)).all())

    async def replace_hypotheses(
        self,
        search_id: UUID | str,
        hypotheses: Iterable[DomainIdentityHypothesis],
        *,
        model_version: str = "deterministic-v0.1",
    ) -> list[IdentityHypothesis]:
        """Replace ranked identity clusters and their explicit memberships."""

        search_uuid = _as_uuid(search_id, "search_id")
        await self._require_search(search_uuid)
        await self.session.execute(
            delete(IdentityHypothesis).where(IdentityHypothesis.search_run_id == search_uuid)
        )
        stored: list[IdentityHypothesis] = []
        ordered = sorted(hypotheses, key=lambda item: item.rank)
        for item in ordered:
            hypothesis = IdentityHypothesis(
                id=_hypothesis_uuid(search_uuid, item.hypothesis_id),
                search_run_id=search_uuid,
                rank=item.rank,
                label=f"Identity {item.rank}",
                overall_score=item.overall_score,
                classification=Classification(item.classification.value),
                status=HypothesisStatus.ACTIVE,
                model_version=model_version,
            )
            hypothesis.memberships = [
                HypothesisMembership(
                    profile_id=_as_uuid(membership.profile_id, "profile_id"),
                    score=membership.score,
                    classification=Classification(membership.classification.value),
                    support_count=membership.support_count,
                    contradiction_count=membership.contradiction_count,
                    model_version=model_version,
                )
                for membership in item.memberships
            ]
            self.session.add(hypothesis)
            stored.append(hypothesis)
        await self.session.flush()
        return stored

    async def list_hypotheses(self, search_id: UUID | str) -> list[IdentityHypothesis]:
        statement = (
            select(IdentityHypothesis)
            .where(IdentityHypothesis.search_run_id == _as_uuid(search_id, "search_id"))
            .options(
                selectinload(IdentityHypothesis.memberships).selectinload(
                    HypothesisMembership.profile
                )
            )
            .order_by(IdentityHypothesis.rank, IdentityHypothesis.id)
        )
        return list((await self.session.scalars(statement)).all())

    async def create_question(
        self,
        search_id: UUID | str,
        *,
        question_type: QuestionType | str,
        question_text: str,
        options: Sequence[Mapping[str, Any]],
        reason: str,
        affected_profile_ids: Sequence[UUID | str] = (),
        affected_hypothesis_ids: Sequence[UUID | str] = (),
        expected_information_gain: float | None = None,
        sensitivity_level: SensitivityLevel | str = SensitivityLevel.LOW,
        context: Mapping[str, Any] | None = None,
    ) -> InvestigationQuestion:
        """Persist one low-sensitivity, high-value ambiguity question."""

        search = await self._require_search(search_id)
        if search.questions_asked >= search.max_questions:
            raise InvalidRepositoryState("maximum investigation-question limit reached")
        pending = await self.get_pending_question(search.id)
        if pending is not None:
            raise InvalidRepositoryState("the search already has a pending question")
        if not question_text.strip() or not reason.strip():
            raise ValueError("question text and reason are required")
        if expected_information_gain is not None and expected_information_gain < 0:
            raise ValueError("expected information gain cannot be negative")

        question = InvestigationQuestion(
            search_run_id=search.id,
            question_type=QuestionType(_enum_value(question_type)),
            question_text=question_text.strip(),
            options=_jsonable(options),
            context=_jsonable(context or {}),
            reason=reason.strip(),
            affected_profile_ids=[
                _as_uuid(item, "affected_profile_id") for item in affected_profile_ids
            ],
            affected_hypothesis_ids=[
                _as_uuid(item, "affected_hypothesis_id") for item in affected_hypothesis_ids
            ],
            expected_information_gain=expected_information_gain,
            sensitivity_level=SensitivityLevel(_enum_value(sensitivity_level)),
            status=QuestionStatus.PENDING,
        )
        search.questions_asked += 1
        self.session.add(question)
        await self.session.flush()
        emit(self.session, search.id, "QUESTION_CREATED", question_id=str(question.id))
        return question

    async def get_pending_question(self, search_id: UUID | str) -> InvestigationQuestion | None:
        statement = (
            select(InvestigationQuestion)
            .where(
                InvestigationQuestion.search_run_id == _as_uuid(search_id, "search_id"),
                InvestigationQuestion.status == QuestionStatus.PENDING,
            )
            .options(selectinload(InvestigationQuestion.answers))
            .order_by(InvestigationQuestion.created_at.desc(), InvestigationQuestion.id.desc())
        )
        return await self.session.scalar(statement)

    async def get_question(self, question_id: UUID | str) -> InvestigationQuestion | None:
        statement = (
            select(InvestigationQuestion)
            .where(InvestigationQuestion.id == _as_uuid(question_id, "question_id"))
            .options(selectinload(InvestigationQuestion.answers))
        )
        return await self.session.scalar(statement)

    async def list_questions(self, search_id: UUID | str) -> list[InvestigationQuestion]:
        statement = (
            select(InvestigationQuestion)
            .where(InvestigationQuestion.search_run_id == _as_uuid(search_id, "search_id"))
            .options(selectinload(InvestigationQuestion.answers))
            .order_by(InvestigationQuestion.created_at, InvestigationQuestion.id)
        )
        return list((await self.session.scalars(statement)).all())

    async def answer_question(
        self,
        question_id: UUID | str,
        answer: Mapping[str, Any] | Any,
        *,
        skipped: bool = False,
    ) -> QuestionAnswerResult:
        """Append an auditable answer and close the pending question."""

        question = await self.get_question(question_id)
        if question is None:
            raise RepositoryEntityNotFound("investigation question not found")
        if question.status is not QuestionStatus.PENDING:
            raise InvalidRepositoryState("investigation question is no longer pending")

        payload = answer if isinstance(answer, Mapping) else {"value": answer}
        record = InvestigationAnswer(question_id=question.id, answer=_jsonable(payload))
        question.answers.append(record)
        question.status = QuestionStatus.SKIPPED if skipped else QuestionStatus.ANSWERED
        question.answered_at = utc_now()
        self.session.add(record)
        await self.session.flush()
        return QuestionAnswerResult(question, record)

    async def create_report(
        self,
        search_id: UUID | str,
        report_data: Mapping[str, Any] | Any,
    ) -> Report:
        """Persist an immutable report snapshot; earlier reports remain auditable."""

        search = await self._require_search(search_id)
        report = Report(search_run_id=search.id, report_data=_jsonable(report_data))
        self.session.add(report)
        await self.session.flush()
        return report

    async def get_latest_report(self, search_id: UUID | str) -> Report | None:
        statement = (
            select(Report)
            .where(Report.search_run_id == _as_uuid(search_id, "search_id"))
            .order_by(Report.generated_at.desc(), Report.id.desc())
            .limit(1)
        )
        return await self.session.scalar(statement)

    async def get_graph(self, search_id: UUID | str) -> GraphSnapshot:
        search = await self.get_search(search_id)
        if search is None:
            raise RepositoryEntityNotFound("search not found")
        profiles = await self.list_profiles_for_search(search.id)
        evidence = await self.list_evidence(search.id)
        hypotheses = await self.list_hypotheses(search.id)
        return build_graph_snapshot(search, profiles, evidence, hypotheses)

    async def _require_search(self, search_id: UUID | str) -> SearchRun:
        search = await self.get_search(search_id)
        if search is None:
            raise RepositoryEntityNotFound("search not found")
        return search

    async def _upsert_profile(self, candidate: CandidateProfile) -> Profile:
        values = _profile_values(candidate)
        platform = values["platform"]
        account_id = values["platform_account_id"]
        canonical_url = values["canonical_url"]

        conditions = [
            (Profile.platform == platform) & (Profile.canonical_url == canonical_url),
        ]
        if account_id:
            conditions.append(
                (Profile.platform == platform) & (Profile.platform_account_id == account_id)
            )
        existing = await self.session.scalar(select(Profile).where(or_(*conditions)))
        if existing is not None:
            if (
                existing.platform_account_id
                and account_id
                and existing.platform_account_id != account_id
            ):
                raise InvalidRepositoryState(
                    "profile URL collision between different platform account IDs"
                )
            await self._merge_profile_values(existing, values)
            return existing

        profile = await self.session.scalar(_profile_upsert_statement(candidate))
        if profile is None:  # pragma: no cover - RETURNING is guaranteed by PostgreSQL
            raise InvalidRepositoryState("PostgreSQL profile upsert returned no profile")
        return profile

    async def upsert_profile(self, candidate: CandidateProfile) -> tuple[Profile, bool]:
        """Public wrapper around profile upsert returning (profile, created_new)."""
        values = _profile_values(candidate)
        platform = values["platform"]
        account_id = values["platform_account_id"]
        canonical_url = values["canonical_url"]

        conditions = [
            (Profile.platform == platform) & (Profile.canonical_url == canonical_url),
        ]
        if account_id:
            conditions.append(
                (Profile.platform == platform) & (Profile.platform_account_id == account_id)
            )
        existing = await self.session.scalar(select(Profile).where(or_(*conditions)))
        profile = await self._upsert_profile(candidate)
        return profile, (existing is None)

    async def create_observation(
        self,
        *,
        search_id: UUID | str,
        profile_id: UUID | str,
        connector: str,
        source_url: str | None = None,
        normalized_data: Mapping[str, Any] | None = None,
        raw_data: Mapping[str, Any] | None = None,
    ) -> ProfileObservation:
        """Public observation creation with automatic synthetic connector run creation."""
        search = await self._require_search(search_id)
        profile_uuid = _as_uuid(profile_id, "profile_id")
        profile = await self.session.get(Profile, profile_uuid)
        if profile is None:
            raise RepositoryEntityNotFound("profile not found")

        connector_run = await self.create_connector_run(
            search_id=search.id,
            connector=connector,
        )
        connector_run.status = ConnectorStatus.SUCCESS
        connector_run.completed_at = utc_now()

        observation = await self._add_profile_observation(
            run=connector_run,
            profile=profile,
            source_url=source_url,
            normalized_data=normalized_data or {},
            raw_data=raw_data or {},
        )
        return observation

    async def _merge_profile_values(self, profile: Profile, values: Mapping[str, Any]) -> None:
        candidate_url = str(values["canonical_url"])
        if profile.canonical_url != candidate_url:
            collision = await self.session.scalar(
                select(Profile.id).where(
                    Profile.platform == profile.platform,
                    Profile.canonical_url == candidate_url,
                    Profile.id != profile.id,
                )
            )
            if collision is not None:
                raise InvalidRepositoryState("canonical profile URL is already assigned")
            profile.canonical_url = candidate_url
        for field in (
            "platform_account_id",
            "username",
            "normalized_username",
            "display_name",
            "normalized_display_name",
            "avatar_url",
            "current_bio",
            "current_location",
            "current_organization",
        ):
            value = values.get(field)
            if value not in (None, ""):
                setattr(profile, field, value)
        profile.last_seen_at = utc_now()

    async def _add_profile_observation(
        self,
        run: ConnectorRun,
        profile: Profile,
        *,
        source_url: str | None,
        normalized_data: Mapping[str, Any],
        raw_data: Mapping[str, Any],
    ) -> ProfileObservation:
        normalized = _jsonable(normalized_data)
        raw = _jsonable(raw_data)
        observation = ProfileObservation(
            search_run_id=run.search_run_id,
            profile_id=profile.id,
            connector_run_id=run.id,
            connector=run.connector,
            source_url=_safe_canonical_url(source_url),
            normalized_data=normalized,
            raw_data=raw,
            content_hash=_content_hash(normalized, raw),
        )
        self.session.add(observation)
        await self.session.flush()
        return observation

    async def _link_identifier(
        self,
        profile: Profile,
        observation: ProfileObservation,
        spec: _IdentifierSpec,
    ) -> None:
        identifier = await self.session.scalar(_identifier_upsert_statement(spec))
        if identifier is None:  # pragma: no cover - RETURNING is guaranteed
            raise InvalidRepositoryState("PostgreSQL identifier upsert returned no row")
        await self.session.execute(
            _profile_identifier_upsert_statement(profile, observation, identifier, spec)
        )

    async def _resolve_artifact_profile(
        self,
        run: ConnectorRun,
        profile_url: str | None,
        profiles_by_url: dict[str, Profile],
    ) -> Profile | None:
        candidate_urls = [profile_url]
        input_profile = (run.input_data or {}).get("profile")
        if isinstance(input_profile, Mapping):
            candidate_urls.append(input_profile.get("canonical_url"))
        candidate_urls.append((run.input_data or {}).get("value"))
        for raw_url in candidate_urls:
            canonical = _safe_canonical_url(raw_url)
            if canonical is None:
                continue
            profile = profiles_by_url.get(canonical)
            if profile is None:
                profile = await self.session.scalar(
                    select(Profile).where(Profile.canonical_url == canonical)
                )
            if profile is not None:
                profiles_by_url[canonical] = profile
                return profile
        if len(profiles_by_url) == 1:
            return next(iter(profiles_by_url.values()))
        return None

    async def _resolve_identifier_profile(
        self,
        run: ConnectorRun,
        artifact: IdentifierArtifact,
        profiles_by_url: dict[str, Profile],
        profiles: Sequence[Profile],
    ) -> Profile | None:
        profile = await self._resolve_artifact_profile(run, artifact.profile_url, profiles_by_url)
        if profile is not None:
            return profile
        if artifact.type is IdentifierType.USERNAME:
            matches = [
                item
                for item in profiles
                if item.normalized_username == normalize_username(artifact.normalized_value)
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    async def _persist_cross_profile_links(
        self,
        run: ConnectorRun,
        candidates: Sequence[CandidateProfile],
        profiles_by_url: Mapping[str, Profile],
    ) -> None:
        for candidate in candidates:
            left = profiles_by_url[canonicalize_url(candidate.canonical_url)]
            for link in candidate.external_links:
                target_url = _safe_canonical_url(link)
                if target_url is None:
                    continue
                right = profiles_by_url.get(target_url)
                if right is None:
                    right = await self.session.scalar(
                        select(Profile).where(Profile.canonical_url == target_url)
                    )
                if right is None or right.id == left.id:
                    continue
                await self.session.execute(
                    _profile_relationship_upsert_statement(
                        left.id,
                        right.id,
                        "PUBLIC_CROSS_LINK",
                        raw_score=1.0,
                        metadata={
                            "connector": run.connector,
                            "connector_run_id": str(run.id),
                            "source_url": candidate.canonical_url,
                            "target_url": target_url,
                        },
                    )
                )

    async def _persist_resolved_relationships(
        self,
        run: ConnectorRun,
        result: ConnectorResult,
        profiles: Sequence[Profile],
    ) -> None:
        identifier_profiles: dict[tuple[str, str], set[UUID]] = {}
        for profile in profiles:
            for spec in _profile_specs_from_stored_profile(profile):
                identifier_profiles.setdefault(
                    (spec.identifier_type, spec.normalized_value), set()
                ).add(profile.id)
        for artifact in result.identifiers:
            profile = next(
                (
                    item
                    for item in profiles
                    if artifact.profile_url
                    and item.canonical_url == _safe_canonical_url(artifact.profile_url)
                ),
                None,
            )
            if profile is not None:
                identifier_profiles.setdefault(
                    (artifact.type.value, artifact.normalized_value), set()
                ).add(profile.id)

        for relationship in result.relationships:
            source_key = (
                relationship.source_type.value,
                _normalize_identifier_value(
                    relationship.source_type.value, relationship.source_value
                ),
            )
            target_key = (
                relationship.target_type.value,
                _normalize_identifier_value(
                    relationship.target_type.value, relationship.target_value
                ),
            )
            for left_id in identifier_profiles.get(source_key, set()):
                for right_id in identifier_profiles.get(target_key, set()):
                    if left_id == right_id:
                        continue
                    await self.session.execute(
                        _profile_relationship_upsert_statement(
                            left_id,
                            right_id,
                            relationship.relationship_type,
                            raw_score=relationship.reliability,
                            metadata={
                                "connector": run.connector,
                                "connector_run_id": str(run.id),
                                "source_url": relationship.source_url,
                                "source_identifier": source_key,
                                "target_identifier": target_key,
                            },
                        )
                    )


def evidence_key(signal: DomainEvidenceSignal) -> tuple[str, str, str, str | None]:
    """Return a stable key for attaching scorer contributions to evidence."""

    left, right = signal.pair_key
    return (left, right, signal.signal_type.value, signal.source_key)


def build_graph_snapshot(
    search: SearchRun,
    profiles: Sequence[Profile],
    evidence: Sequence[EvidenceSignal],
    hypotheses: Sequence[IdentityHypothesis],
) -> GraphSnapshot:
    """Build a transport-neutral identity graph from already-loaded rows."""

    search_id = str(search.id)
    nodes: list[GraphNodeData] = [
        GraphNodeData(
            id=search_id,
            type="search",
            label="Investigation",
            properties={"status": _enum_value(search.status), "scope": search.scope},
        )
    ]
    edges: list[GraphEdgeData] = []
    for profile in profiles:
        profile_id = str(profile.id)
        nodes.append(
            GraphNodeData(
                id=profile_id,
                type="profile",
                label=profile.username or profile.display_name or profile.platform,
                properties={
                    "platform": profile.platform,
                    "canonical_url": profile.canonical_url,
                    "display_name": profile.display_name,
                },
            )
        )
        edges.append(
            GraphEdgeData(
                id=f"search-profile:{search_id}:{profile_id}",
                source=search_id,
                target=profile_id,
                type="OBSERVED_PROFILE",
            )
        )

    for hypothesis in sorted(hypotheses, key=lambda item: item.rank):
        hypothesis_id = str(hypothesis.id)
        nodes.append(
            GraphNodeData(
                id=hypothesis_id,
                type="hypothesis",
                label=hypothesis.label or f"Identity {hypothesis.rank}",
                properties={
                    "rank": hypothesis.rank,
                    "score": hypothesis.overall_score,
                    "classification": _enum_value(hypothesis.classification),
                },
            )
        )
        for membership in hypothesis.memberships:
            edges.append(
                GraphEdgeData(
                    id=f"membership:{hypothesis_id}:{membership.profile_id}",
                    source=hypothesis_id,
                    target=str(membership.profile_id),
                    type="HAS_CANDIDATE",
                    score=membership.score,
                    classification=_enum_value(membership.classification),
                    properties={
                        "support_count": membership.support_count,
                        "contradiction_count": membership.contradiction_count,
                    },
                )
            )

    for item in evidence:
        direction = _enum_value(item.direction)
        score = item.model_contribution
        if score is None:
            score = item.normalized_score * (-1 if direction == "CONTRADICT" else 1)
        edges.append(
            GraphEdgeData(
                id=f"evidence:{item.id}",
                source=str(item.left_profile_id),
                target=str(item.right_profile_id),
                type=item.signal_type,
                score=score,
                properties={
                    "direction": direction,
                    "reliability": item.reliability,
                    "evidence_family": item.evidence_family,
                    "explanation": item.explanation,
                },
            )
        )
    return GraphSnapshot(tuple(nodes), tuple(edges))


def _profile_values(candidate: CandidateProfile) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "platform": candidate.platform.strip().casefold(),
        "platform_account_id": _optional_text(candidate.platform_account_id),
        "username": _optional_text(candidate.username),
        "normalized_username": normalize_username(candidate.username) or None,
        "display_name": _optional_text(candidate.display_name),
        "normalized_display_name": normalize_name(candidate.display_name) or None,
        "canonical_url": canonicalize_url(candidate.canonical_url),
        "avatar_url": _safe_canonical_url(candidate.avatar_url),
        "current_bio": _optional_text(candidate.bio),
        "current_location": _optional_text(candidate.location),
        "current_organization": _optional_text(candidate.employer),
        "last_seen_at": utc_now(),
    }


def _profile_upsert_statement(candidate: CandidateProfile) -> Any:
    values = _profile_values(candidate)
    statement = pg_insert(Profile).values(**values)
    excluded = statement.excluded
    return statement.on_conflict_do_update(
        index_elements=[Profile.platform, Profile.canonical_url],
        set_={
            "platform_account_id": func.coalesce(
                excluded.platform_account_id, Profile.platform_account_id
            ),
            "username": func.coalesce(excluded.username, Profile.username),
            "normalized_username": func.coalesce(
                excluded.normalized_username, Profile.normalized_username
            ),
            "display_name": func.coalesce(excluded.display_name, Profile.display_name),
            "normalized_display_name": func.coalesce(
                excluded.normalized_display_name, Profile.normalized_display_name
            ),
            "avatar_url": func.coalesce(excluded.avatar_url, Profile.avatar_url),
            "current_bio": func.coalesce(excluded.current_bio, Profile.current_bio),
            "current_location": func.coalesce(excluded.current_location, Profile.current_location),
            "current_organization": func.coalesce(
                excluded.current_organization, Profile.current_organization
            ),
            "last_seen_at": excluded.last_seen_at,
        },
    ).returning(Profile)


def _identifier_upsert_statement(spec: _IdentifierSpec) -> Any:
    statement = pg_insert(Identifier).values(
        id=uuid.uuid4(),
        identifier_type=spec.identifier_type,
        normalized_value=spec.normalized_value,
        display_value=spec.value,
        metadata_json=_jsonable(spec.metadata),
    )
    excluded = statement.excluded
    return statement.on_conflict_do_update(
        index_elements=[Identifier.identifier_type, Identifier.normalized_value],
        set_={
            "display_value": func.coalesce(excluded.display_value, Identifier.display_value),
            "metadata": excluded.metadata,
        },
    ).returning(Identifier)


def _profile_identifier_upsert_statement(
    profile: Profile,
    observation: ProfileObservation,
    identifier: Identifier,
    spec: _IdentifierSpec,
) -> Any:
    statement = pg_insert(ProfileIdentifier).values(
        profile_id=profile.id,
        identifier_id=identifier.id,
        relationship_type=spec.relationship_type,
        observation_id=observation.id,
        confidence=spec.confidence,
    )
    return statement.on_conflict_do_update(
        index_elements=[
            ProfileIdentifier.profile_id,
            ProfileIdentifier.identifier_id,
            ProfileIdentifier.relationship_type,
        ],
        set_={
            "observation_id": statement.excluded.observation_id,
            "confidence": func.greatest(
                ProfileIdentifier.confidence, statement.excluded.confidence
            ),
        },
    )


def _profile_relationship_upsert_statement(
    left_profile_id: UUID,
    right_profile_id: UUID,
    relationship_type: str,
    *,
    raw_score: float | None,
    metadata: Mapping[str, Any],
) -> Any:
    statement = pg_insert(ProfileRelationship).values(
        id=uuid.uuid4(),
        left_profile_id=left_profile_id,
        right_profile_id=right_profile_id,
        relationship_type=relationship_type,
        raw_score=raw_score,
        metadata_json=_jsonable(metadata),
    )
    return statement.on_conflict_do_update(
        index_elements=[
            ProfileRelationship.left_profile_id,
            ProfileRelationship.right_profile_id,
            ProfileRelationship.relationship_type,
        ],
        set_={
            "raw_score": statement.excluded.raw_score,
            "metadata": statement.excluded.metadata,
        },
    )


def _candidate_identifier_specs(candidate: CandidateProfile) -> tuple[_IdentifierSpec, ...]:
    specs: list[_IdentifierSpec] = []

    def add(
        kind: str,
        value: str | None,
        normalized: str,
        relationship: str = "PROFILE_FIELD",
        confidence: float = 1.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if value and normalized:
            specs.append(
                _IdentifierSpec(
                    kind,
                    value,
                    normalized,
                    relationship,
                    confidence,
                    metadata or {},
                )
            )

    add("USERNAME", candidate.username, normalize_username(candidate.username))
    add("DISPLAY_NAME", candidate.display_name, normalize_name(candidate.display_name))
    canonical_url = canonicalize_url(candidate.canonical_url)
    add("URL", canonical_url, canonical_url)
    for external_link in candidate.external_links:
        canonical_link = _safe_canonical_url(external_link)
        if canonical_link:
            add("URL", external_link, canonical_link, "PUBLIC_EXTERNAL_LINK", 0.9)
        domain = normalize_domain(external_link)
        if is_personal_domain(domain):
            add("DOMAIN", domain, domain, "PUBLIC_EXTERNAL_LINK", 0.9)
    return tuple(
        {
            (
                spec.identifier_type,
                spec.normalized_value,
                spec.relationship_type,
            ): spec
            for spec in specs
        }.values()
    )


def _profile_specs_from_stored_profile(profile: Profile) -> tuple[_IdentifierSpec, ...]:
    candidate = CandidateProfile(
        platform=profile.platform,
        platform_account_id=profile.platform_account_id,
        username=profile.username,
        display_name=profile.display_name,
        canonical_url=profile.canonical_url,
        bio=profile.current_bio,
        location=profile.current_location,
        employer=profile.current_organization,
        avatar_url=profile.avatar_url,
    )
    return _candidate_identifier_specs(candidate)


def _candidate_normalized_data(candidate: CandidateProfile) -> dict[str, Any]:
    return candidate.model_dump(mode="json", exclude={"raw"})


def _deduplicate_candidates(
    candidates: Sequence[CandidateProfile],
) -> tuple[CandidateProfile, ...]:
    by_key: dict[tuple[str, str, str], CandidateProfile] = {}
    positions_by_url: dict[tuple[str, str], tuple[str, str, str]] = {}
    for candidate in candidates:
        platform = candidate.platform.casefold()
        canonical_url = canonicalize_url(candidate.canonical_url)
        key = (
            platform,
            "account" if candidate.platform_account_id else "url",
            candidate.platform_account_id or canonical_url,
        )
        url_key = (platform, canonical_url)
        existing_key = key if key in by_key else positions_by_url.get(url_key)
        if existing_key is None:
            normalized = candidate.model_copy(
                update={"platform": platform, "canonical_url": canonical_url}
            )
            by_key[key] = normalized
            positions_by_url[url_key] = key
            continue
        existing = by_key[existing_key]
        by_key[existing_key] = _merge_candidates(existing, candidate)
    return tuple(by_key.values())


def _merge_candidates(left: CandidateProfile, right: CandidateProfile) -> CandidateProfile:
    if (
        left.platform_account_id
        and right.platform_account_id
        and left.platform_account_id != right.platform_account_id
    ):
        raise InvalidRepositoryState(
            "connector returned one canonical URL for different platform accounts"
        )

    def prefer(left_value: Any, right_value: Any) -> Any:
        return left_value if left_value not in (None, "", [], {}) else right_value

    return left.model_copy(
        update={
            "platform_account_id": prefer(left.platform_account_id, right.platform_account_id),
            "username": prefer(left.username, right.username),
            "display_name": prefer(left.display_name, right.display_name),
            "bio": prefer(left.bio, right.bio),
            "location": prefer(left.location, right.location),
            "employer": prefer(left.employer, right.employer),
            "external_links": list(dict.fromkeys(left.external_links + right.external_links)),
            "avatar_url": prefer(left.avatar_url, right.avatar_url),
            "source_url": prefer(left.source_url, right.source_url),
            "discovered_by": list(dict.fromkeys(left.discovered_by + right.discovered_by)),
            "raw": {**right.raw, **left.raw},
        }
    )


def _build_profile_snapshot(
    profile: Profile,
    observations: Sequence[ProfileObservation],
) -> ProfileSnapshot:
    links: list[str] = []
    projects: list[str] = []
    topics: list[str] = []
    discovered_by: list[str] = []
    # Global profile columns are a convenience cache, not evidence for this run.
    # Only claims actually observed in this search can enter its correlation snapshot.
    observed_fields: dict[str, Any] = {}
    for observation in observations:
        data = observation.normalized_data or {}
        for field in ("username", "display_name", "bio", "location", "employer", "avatar_url"):
            if data.get(field) not in (None, ""):
                observed_fields[field] = data[field]
        links.extend(_string_values(data.get("external_links")))
        discovered_by.extend(_string_values(data.get("discovered_by")))
        signal_type = str(data.get("signal_type") or "").casefold()
        value = data.get("value")
        if signal_type == "public_external_link":
            links.extend(_string_values(value))
        elif signal_type != "repository_social_reference" and (
            "repositor" in signal_type or signal_type == "project"
        ):
            projects.extend(_string_values(value))
        elif "topic" in signal_type:
            topics.extend(_string_values(value))
    return ProfileSnapshot(
        id=profile.id,
        platform=profile.platform,
        platform_account_id=profile.platform_account_id,
        username=observed_fields.get("username"),
        normalized_username=normalize_username(observed_fields.get("username")),
        display_name=observed_fields.get("display_name"),
        normalized_display_name=normalize_name(observed_fields.get("display_name")),
        canonical_url=profile.canonical_url,
        bio=observed_fields.get("bio"),
        location=observed_fields.get("location"),
        organization=observed_fields.get("employer"),
        avatar_url=observed_fields.get("avatar_url"),
        external_links=tuple(dict.fromkeys(_canonical_urls(links))),
        projects=tuple(dict.fromkeys(projects)),
        topics=tuple(dict.fromkeys(topics)),
        discovered_by=tuple(dict.fromkeys(discovered_by)),
        source_observation_ids=tuple(str(item.id) for item in observations),
    )


def _classification_for_score(score: float) -> Classification:
    if score <= -0.10:
        return Classification.CONTRADICTORY
    if score >= 0.40:
        return Classification.STRONG
    if score >= 0.20:
        return Classification.LIKELY
    if score >= 0.07:
        return Classification.AMBIGUOUS
    return Classification.WEAK


def _bounded_score(value: float) -> float:
    return round(max(-1.0, min(1.0, value)), 6)


def _hypothesis_uuid(search_id: UUID, hypothesis_id: str) -> UUID:
    try:
        return UUID(hypothesis_id)
    except (TypeError, ValueError, AttributeError):
        return uuid.uuid5(search_id, hypothesis_id)


def _lookup_contribution(
    contributions: Mapping[Any, float],
    signal: DomainEvidenceSignal,
    key: tuple[str, str, str, str | None],
) -> float | None:
    value = contributions.get(key)
    if value is None:
        value = contributions.get(id(signal))
    return float(value) if value is not None else None


def _normalize_identifier_value(identifier_type: str, value: str) -> str:
    if identifier_type == "USERNAME":
        return normalize_username(value)
    if identifier_type == "DISPLAY_NAME":
        return normalize_name(value)
    if identifier_type == "URL":
        return canonicalize_url(value)
    if identifier_type == "DOMAIN":
        return normalize_domain(value)
    return value.strip().casefold()


def _safe_canonical_url(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        return canonicalize_url(str(value))
    except (TypeError, ValueError):
        return None


def _canonical_urls(values: Iterable[str]) -> list[str]:
    return [item for value in values if (item := _safe_canonical_url(value)) is not None]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        return [str(item) for item in value if item is not None and str(item).strip()]
    return [str(value)]


def _content_hash(normalized: Mapping[str, Any], raw: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"normalized": normalized, "raw": raw},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _as_uuid(value: UUID | str, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


def _enum_value(value: Any) -> str:
    return str(value.value if isinstance(value, Enum) else value)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _validate_limits(limits: SearchLimits) -> None:
    if limits.max_pivot_depth < 0:
        raise ValueError("max_pivot_depth cannot be negative")
    if limits.max_questions < 0:
        raise ValueError("max_questions cannot be negative")
    if limits.max_connector_runs < 1:
        raise ValueError("max_connector_runs must be positive")
    if limits.max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    if limits.max_search_duration_seconds < 1:
        raise ValueError("max_search_duration_seconds must be positive")


_ERROR_CONNECTOR_STATUSES = {
    ConnectorStatus.RATE_LIMITED,
    ConnectorStatus.AUTH_REQUIRED,
    ConnectorStatus.UNAVAILABLE,
    ConnectorStatus.DISABLED,
    ConnectorStatus.FAILED,
}
