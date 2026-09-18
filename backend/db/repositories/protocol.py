"""Structural interface used by orchestration and API services."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from backend.connectors.schemas import CandidateProfile
from backend.connectors.schemas import ConnectorResult
from backend.core.enums import (
    QuestionType,
    SeedType,
    SensitivityLevel,
)
from backend.correlation.features import EvidenceSignal, IdentityHypothesis, PairAssessment
from backend.db.models import (
    ConnectorRun,
    InvestigationQuestion,
    Profile,
    ProfileObservation,
    Report,
    SearchRun,
)
from backend.db.models import (
    EvidenceSignal as StoredEvidenceSignal,
)
from backend.db.models import (
    IdentityHypothesis as StoredIdentityHypothesis,
)

from .types import (
    PersistedConnectorResult,
    ProfileSnapshot,
    QuestionAnswerResult,
    SearchLimits,
)


class InvestigationRepository(Protocol):
    """Transaction-neutral async persistence contract.

    Implementations flush writes but leave commit/rollback control to the
    request or worker transaction that owns the repository.
    """

    async def create_search(
        self,
        seed_type: SeedType | str,
        original_value: str,
        normalized_value: str | None = None,
        *,
        scope: str = "self_audit",
        limits: SearchLimits | None = None,
        retention_expires_at: datetime | None = None,
    ) -> SearchRun: ...

    async def get_search(self, search_id: UUID | str) -> SearchRun | None: ...

    async def update_search(self, search_id: UUID | str, **fields: Any) -> SearchRun: ...

    async def create_connector_run(
        self,
        search_id: UUID | str,
        connector: str,
        *,
        connector_version: str | None = None,
        input_data: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any: ...

    async def persist_connector_result(
        self,
        connector_run_id: UUID | str,
        result: ConnectorResult,
    ) -> PersistedConnectorResult: ...

    async def list_connector_runs(self, search_id: UUID | str) -> list[ConnectorRun]: ...

    async def list_profiles_for_search(self, search_id: UUID | str) -> list[Profile]: ...

    async def upsert_profile(
        self, candidate: CandidateProfile
    ) -> tuple[Profile, bool]: ...

    async def create_observation(
        self,
        *,
        search_id: UUID | str,
        profile_id: UUID | str,
        connector: str,
        source_url: str | None = None,
        normalized_data: Mapping[str, Any] | None = None,
        raw_data: Mapping[str, Any] | None = None,
    ) -> ProfileObservation: ...

    async def list_profile_snapshots_for_search(
        self, search_id: UUID | str
    ) -> list[ProfileSnapshot]: ...

    async def list_observations_for_search(
        self, search_id: UUID | str
    ) -> list[ProfileObservation]: ...

    async def replace_evidence(
        self,
        search_id: UUID | str,
        signals: Iterable[EvidenceSignal],
        *,
        contribution_by_key: Mapping[Any, float] | None = None,
        extractor_version: str = "deterministic-v0.1",
    ) -> list[StoredEvidenceSignal]: ...

    async def replace_pair_assessments(
        self, search_id: UUID | str, assessments: Iterable[PairAssessment]
    ) -> list[StoredEvidenceSignal]: ...

    async def list_evidence(self, search_id: UUID | str) -> list[StoredEvidenceSignal]: ...

    async def replace_hypotheses(
        self,
        search_id: UUID | str,
        hypotheses: Iterable[IdentityHypothesis],
        *,
        model_version: str = "deterministic-v0.1",
    ) -> list[StoredIdentityHypothesis]: ...

    async def list_hypotheses(self, search_id: UUID | str) -> list[StoredIdentityHypothesis]: ...

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
    ) -> InvestigationQuestion: ...

    async def get_pending_question(self, search_id: UUID | str) -> InvestigationQuestion | None: ...

    async def get_question(self, question_id: UUID | str) -> InvestigationQuestion | None: ...

    async def list_questions(self, search_id: UUID | str) -> list[InvestigationQuestion]: ...

    async def answer_question(
        self,
        question_id: UUID | str,
        answer: Mapping[str, Any] | Any,
        *,
        skipped: bool = False,
    ) -> QuestionAnswerResult: ...

    async def create_report(
        self, search_id: UUID | str, report_data: Mapping[str, Any] | Any
    ) -> Report: ...

    async def get_latest_report(self, search_id: UUID | str) -> Report | None: ...
