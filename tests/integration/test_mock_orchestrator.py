from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.dependencies import get_repository
from backend.app.main import app
from backend.core.config import Settings, get_settings
from backend.core.enums import (
    Classification,
    QuestionStatus,
    SearchStatus,
    SeedType,
)
from backend.db.repositories import ProfileSnapshot, SearchLimits
from backend.investigation.orchestrator import SearchOrchestrator
from backend.normalization import canonicalize_url, normalize_name, normalize_username


class MemoryInvestigationRepository:
    """Transaction-free test double; production persistence remains PostgreSQL only."""

    def __init__(self) -> None:
        self.search = None
        self.profiles = {}
        self.profile_payloads = {}
        self.observations = []
        self.connector_runs = []
        self.evidence = []
        self.hypotheses = []
        self.questions = []
        self.reports = []

    async def create_search(
        self,
        seed_type,
        original_value,
        normalized_value=None,
        *,
        scope="self_audit",
        limits=None,
        retention_expires_at=None,
    ):
        limits = limits or SearchLimits()
        now = datetime.now(UTC)
        self.search = SimpleNamespace(
            id=uuid4(),
            status=SearchStatus.CREATED,
            scope=scope,
            created_at=now,
            started_at=None,
            completed_at=None,
            retention_expires_at=retention_expires_at,
            pivot_depth=0,
            questions_asked=0,
            connector_runs_count=0,
            max_pivot_depth=limits.max_pivot_depth,
            max_questions=limits.max_questions,
            max_connector_runs=limits.max_connector_runs,
            max_candidates=limits.max_candidates,
            max_search_duration_seconds=limits.max_search_duration_seconds,
            error_summary=None,
            seeds=[
                SimpleNamespace(
                    seed_type=SeedType(seed_type),
                    original_value=original_value,
                    normalized_value=normalized_value,
                )
            ],
        )
        return self.search

    async def get_search(self, search_id):
        if self.search and str(self.search.id) == str(search_id):
            return self.search
        return None

    async def update_search(self, search_id, **fields):
        search = await self.get_search(search_id)
        if search is None:
            raise LookupError("search not found")
        for key, value in fields.items():
            setattr(search, key, value)
        if search.status is not SearchStatus.CREATED and search.started_at is None:
            search.started_at = datetime.now(UTC)
        if search.status in {
            SearchStatus.COMPLETED,
            SearchStatus.CANCELLED,
            SearchStatus.FAILED,
        }:
            search.completed_at = datetime.now(UTC)
        return search

    async def create_connector_run(
        self,
        search_id,
        connector,
        *,
        connector_version=None,
        input_data=None,
        metadata=None,
    ):
        self.search.connector_runs_count += 1
        run = SimpleNamespace(
            id=uuid4(),
            search_run_id=UUID(str(search_id)),
            connector=connector,
            connector_version=connector_version,
            input_data=input_data or {},
            metadata_json=metadata or {},
            status="RUNNING",
        )
        self.connector_runs.append(run)
        return run

    async def persist_connector_result(self, connector_run_id, result):
        run = next(item for item in self.connector_runs if item.id == connector_run_id)
        run.status = result.status
        run.error = result.message
        for candidate in result.profiles:
            url = canonicalize_url(candidate.canonical_url)
            profile = self.profiles.get(url)
            if profile is None:
                profile = SimpleNamespace(
                    id=uuid4(),
                    platform=candidate.platform.casefold(),
                    canonical_url=url,
                    platform_account_id=candidate.platform_account_id,
                    username=candidate.username,
                    normalized_username=normalize_username(candidate.username),
                    display_name=candidate.display_name,
                    normalized_display_name=normalize_name(candidate.display_name),
                    current_bio=candidate.bio,
                    current_location=candidate.location,
                    current_organization=candidate.employer,
                    avatar_url=candidate.avatar_url,
                )
                self.profiles[url] = profile
            self.profile_payloads[profile.id] = candidate
            self._observation(
                run,
                profile.id,
                candidate.source_url or url,
                candidate.model_dump(mode="json", exclude={"raw"}),
            )
        for artifact in result.observations:
            url = canonicalize_url(artifact.profile_url or artifact.source_url)
            profile = self.profiles.get(url)
            if profile:
                self._observation(
                    run,
                    profile.id,
                    artifact.source_url or url,
                    {
                        "signal_type": artifact.signal_type,
                        "value": artifact.value,
                        "reliability": artifact.reliability,
                    },
                )
        return SimpleNamespace(connector_run=run, profiles=(), observations=())

    def _observation(self, run, profile_id, source_url, normalized_data):
        self.observations.append(
            SimpleNamespace(
                id=uuid4(),
                profile_id=profile_id,
                connector=run.connector,
                source_url=source_url,
                normalized_data=normalized_data,
            )
        )

    async def list_connector_runs(self, search_id):
        return list(self.connector_runs)

    async def list_profiles_for_search(self, search_id):
        return list(self.profiles.values())

    async def list_observations_for_search(self, search_id):
        return list(self.observations)

    async def list_profile_snapshots_for_search(self, search_id):
        snapshots = []
        for profile in self.profiles.values():
            payload = self.profile_payloads[profile.id]
            observations = [
                item for item in self.observations if item.profile_id == profile.id
            ]
            projects = []
            for observation in observations:
                if "repositor" in str(
                    observation.normalized_data.get("signal_type", "")
                ):
                    value = observation.normalized_data.get("value", [])
                    projects.extend(value if isinstance(value, list) else [value])
            snapshots.append(
                ProfileSnapshot(
                    id=profile.id,
                    platform=profile.platform,
                    canonical_url=profile.canonical_url,
                    platform_account_id=profile.platform_account_id,
                    username=profile.username,
                    normalized_username=profile.normalized_username,
                    display_name=profile.display_name,
                    normalized_display_name=profile.normalized_display_name,
                    bio=profile.current_bio,
                    location=profile.current_location,
                    organization=profile.current_organization,
                    avatar_url=profile.avatar_url,
                    external_links=tuple(payload.external_links),
                    projects=tuple(projects),
                    discovered_by=tuple(payload.discovered_by),
                    source_observation_ids=tuple(str(item.id) for item in observations),
                )
            )
        return snapshots

    async def replace_pair_assessments(self, search_id, assessments):
        self.evidence = []
        for assessment in assessments:
            contribution = {
                item.evidence.source_key: item.weighted_score
                for item in assessment.contributions
            }
            for signal in assessment.evidence:
                left, right = signal.pair_key
                self.evidence.append(
                    SimpleNamespace(
                        id=uuid4(),
                        left_profile_id=UUID(left),
                        right_profile_id=UUID(right),
                        signal_type=signal.signal_type.value,
                        direction=signal.direction,
                        normalized_score=signal.normalized_score,
                        reliability=signal.reliability,
                        model_contribution=contribution.get(signal.source_key),
                        evidence_family=signal.evidence_family.value,
                        source_observation_ids=[
                            UUID(item) for item in signal.source_observation_ids
                        ],
                        explanation=signal.explanation,
                    )
                )
        return self.evidence

    async def list_evidence(self, search_id):
        return list(self.evidence)

    async def replace_hypotheses(self, search_id, hypotheses, **kwargs):
        del kwargs
        self.hypotheses = []
        for item in hypotheses:
            stored_id = uuid5(UUID(str(search_id)), item.hypothesis_id)
            memberships = []
            for member in item.memberships:
                profile = next(
                    value
                    for value in self.profiles.values()
                    if str(value.id) == member.profile_id
                )
                memberships.append(
                    SimpleNamespace(
                        profile_id=profile.id,
                        profile=profile,
                        score=member.score,
                        classification=Classification(member.classification.value),
                        support_count=member.support_count,
                        contradiction_count=member.contradiction_count,
                    )
                )
            self.hypotheses.append(
                SimpleNamespace(
                    id=stored_id,
                    rank=item.rank,
                    label=f"Identity {item.rank}",
                    overall_score=item.overall_score,
                    classification=Classification(item.classification.value),
                    memberships=memberships,
                )
            )
        return self.hypotheses

    async def list_hypotheses(self, search_id):
        return sorted(self.hypotheses, key=lambda item: item.rank)

    async def create_question(self, search_id, **values):
        self.search.questions_asked += 1
        question = SimpleNamespace(
            id=uuid4(),
            search_run_id=UUID(str(search_id)),
            status=QuestionStatus.PENDING,
            answers=[],
            **values,
        )
        self.questions.append(question)
        return question

    async def get_pending_question(self, search_id):
        return next(
            (item for item in self.questions if item.status is QuestionStatus.PENDING),
            None,
        )

    async def get_question(self, question_id):
        return next(
            (item for item in self.questions if str(item.id) == str(question_id)), None
        )

    async def list_questions(self, search_id):
        return list(self.questions)

    async def answer_question(self, question_id, answer, *, skipped=False):
        question = await self.get_question(question_id)
        question.status = QuestionStatus.SKIPPED if skipped else QuestionStatus.ANSWERED
        question.answers.append(SimpleNamespace(answer=answer))
        return SimpleNamespace(question=question, answer=question.answers[-1])

    async def apply_branch_selection(
        self, search_id, selected_hypothesis_id, *, skipped=False
    ):
        if skipped:
            return self.hypotheses
        for hypothesis in self.hypotheses:
            if selected_hypothesis_id is None:
                delta = -0.10
            elif str(hypothesis.id) == str(selected_hypothesis_id):
                delta = 0.20
            else:
                delta = -0.12
            hypothesis.overall_score = max(-1, min(1, hypothesis.overall_score + delta))
            for membership in hypothesis.memberships:
                membership.score = max(-1, min(1, membership.score + delta))
        self.hypotheses.sort(key=lambda item: -item.overall_score)
        for rank, hypothesis in enumerate(self.hypotheses, 1):
            hypothesis.rank = rank
        return self.hypotheses

    async def create_report(self, search_id, report_data):
        report = SimpleNamespace(report_data=report_data)
        self.reports.append(report)
        return report

    async def get_latest_report(self, search_id):
        return self.reports[-1] if self.reports else None


@pytest.mark.asyncio
async def test_mock_alice_flow_asks_once_and_follows_selected_branch() -> None:
    repository = MemoryInvestigationRepository()
    settings = Settings(mock_connectors=True)
    orchestrator = SearchOrchestrator(repository, settings)

    search = await orchestrator.create_and_run(SeedType.USERNAME, "alice_dev")

    assert search.status is SearchStatus.AWAITING_USER
    assert len(repository.profiles) == 3
    assert len(repository.hypotheses) == 2
    assert repository.hypotheses[0].overall_score - repository.hypotheses[1].overall_score <= 0.4
    assert not any(run.connector == "gitfive" for run in repository.connector_runs)

    question = await repository.get_pending_question(search.id)
    assert question is not None
    assert len(repository.questions) == 1
    toronto = next(item for item in question.options if item["label"] == "Toronto, Canada")

    completed = await orchestrator.answer_question(
        search.id,
        question.id,
        toronto["value"],
    )

    assert completed.status is SearchStatus.COMPLETED
    gitfive_runs = [
        run for run in repository.connector_runs if run.connector == "gitfive"
    ]
    assert len(gitfive_runs) == 1
    assert gitfive_runs[0].input_data["value"] == "https://github.com/alice123"
    report = repository.reports[-1].report_data
    assert report["primary_hypothesis"]["profiles"][0]["username"] == "alice123"
    assert report["answer_impact"]


@pytest.mark.asyncio
async def test_continue_skips_question_without_changing_initial_leader() -> None:
    repository = MemoryInvestigationRepository()
    orchestrator = SearchOrchestrator(repository, Settings(mock_connectors=True))
    search = await orchestrator.create_and_run(SeedType.USERNAME, "alice_dev")
    initial_leader = repository.hypotheses[0].id

    completed = await orchestrator.continue_search(search.id)

    assert completed.status is SearchStatus.COMPLETED
    assert repository.hypotheses[0].id == initial_leader
    assert repository.questions[0].status is QuestionStatus.SKIPPED


@pytest.mark.asyncio
async def test_fastapi_mock_flow_reaches_report() -> None:
    repository = MemoryInvestigationRepository()
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: Settings(mock_connectors=True)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/searches",
                json={"seed_type": "username", "value": "alice_dev"},
            )
            assert created.status_code == 201
            search_id = created.json()["id"]
            question_response = await client.get(
                f"/api/searches/{search_id}/question"
            )
            question = question_response.json()["item"]
            assert question is not None
            toronto = next(
                option for option in question["options"] if option["label"] == "Toronto, Canada"
            )

            answered = await client.post(
                f"/api/searches/{search_id}/question-answer",
                json={"question_id": question["id"], "value": toronto["value"]},
            )

            assert answered.status_code == 200
            assert answered.json()["status"] == "COMPLETED"
            report_response = await client.get(f"/api/searches/{search_id}/report")
            report = report_response.json()["report_data"]
            assert report["primary_hypothesis"]["profiles"][0]["username"] == "alice123"
    finally:
        app.dependency_overrides.clear()
