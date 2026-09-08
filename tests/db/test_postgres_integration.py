"""Real PostgreSQL checks, enabled explicitly with TEST_DATABASE_URL."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.connectors import ConnectorInput, ConnectorInputType, build_default_registry
from backend.connectors.schemas import CandidateProfile, ConnectorResult, ConnectorRunStatus
from backend.correlation import (
    build_identity_hypotheses,
    generate_candidate_pairs,
    score_evidence,
)
from backend.db.models import Base, ProfileIdentifier, ProfileObservation
from backend.db.repositories import PostgresInvestigationRepository
from backend.embeddings import PgVectorRepository
from backend.extraction import extract_pair_evidence
from backend.normalization import normalize_profile

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="set TEST_DATABASE_URL to run isolated PostgreSQL integration tests",
    ),
]


@pytest_asyncio.fixture
async def postgres_session():
    schema = f"osin_test_{uuid4().hex}"
    admin_engine = create_async_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin_engine.dispose()

    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()

    cleanup_engine = create_async_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with cleanup_engine.connect() as connection:
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await cleanup_engine.dispose()


@pytest.mark.asyncio
async def test_repository_provenance_correlation_question_and_vector_round_trip(
    postgres_session: AsyncSession,
) -> None:
    repository = PostgresInvestigationRepository(postgres_session)
    search = await repository.create_search("USERNAME", "alice_dev")
    connector_input = ConnectorInput(type=ConnectorInputType.USERNAME, value="alice_dev")
    registry = build_default_registry(mock_connectors=True)

    for connector_name in ("maigret", "sherlock"):
        connector = registry.get(connector_name)
        run = await repository.create_connector_run(
            search.id,
            connector.name,
            connector_version=connector.version,
            input_data=connector_input.model_dump(mode="json"),
        )
        await repository.persist_connector_result(
            run.id,
            await connector.discover(connector_input),
        )

    profiles = await repository.list_profiles_for_search(search.id)
    assert len(profiles) == 3
    observation_count = await postgres_session.scalar(
        select(func.count(ProfileObservation.id)).where(
            ProfileObservation.search_run_id == search.id
        )
    )
    identifier_link_count = await postgres_session.scalar(
        select(func.count()).select_from(ProfileIdentifier)
    )
    assert observation_count and observation_count >= 10
    assert identifier_link_count and identifier_link_count >= 3

    snapshots = await repository.list_profile_snapshots_for_search(search.id)
    normalized = tuple(normalize_profile(item) for item in snapshots)
    assessments = []
    for pair in generate_candidate_pairs(normalized):
        assessments.append(score_evidence(extract_pair_evidence(pair.left, pair.right)))
    stored_evidence = await repository.replace_pair_assessments(search.id, assessments)
    hypotheses = build_identity_hypotheses(normalized, assessments)
    stored_hypotheses = await repository.replace_hypotheses(search.id, hypotheses)
    assert stored_evidence
    assert len(stored_hypotheses) == 2

    question = await repository.create_question(
        search.id,
        question_type="SINGLE_SELECT",
        question_text="Which broad public location applies?",
        options=[{"value": "skip", "label": "Skip"}],
        reason="One answer would distinguish two public candidate branches.",
    )
    await repository.answer_question(question.id, {"value": "skip"}, skipped=True)
    assert (await repository.get_question(question.id)).answers

    vector_repository = PgVectorRepository(postgres_session)
    vector = [0.0] * 384
    vector[0] = 1.0
    await vector_repository.upsert_text(
        profile_id=profiles[0].id,
        source_field="bio",
        model_name="fixture-model",
        model_version="v1",
        embedding=vector,
    )
    neighbors = await vector_repository.nearest_text(
        vector,
        model_name="fixture-model",
        model_version="v1",
        source_field="bio",
        platform=profiles[0].platform,
    )
    assert neighbors[0].owner_id == profiles[0].id
    assert neighbors[0].distance == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_different_accounts_stay_separate_and_old_claims_do_not_leak(postgres_session):
    repository = PostgresInvestigationRepository(postgres_session)
    first = await repository.create_search("USERNAME", "first")
    run = await repository.create_connector_run(first.id, "contract-test")
    await repository.persist_connector_result(
        run.id,
        ConnectorResult(
            connector="contract-test",
            connector_version="test-only",
            status=ConnectorRunStatus.SUCCESS,
            profiles=[
                CandidateProfile(
                    platform="github",
                    canonical_url="https://github.com/first",
                    username="first",
                    bio="Only observed in first search",
                ),
                CandidateProfile(
                    platform="github", canonical_url="https://github.com/second", username="second"
                ),
            ],
        ),
    )
    assert len(await repository.list_profiles_for_search(first.id)) == 2
    second = await repository.create_search("USERNAME", "first")
    run = await repository.create_connector_run(second.id, "contract-test")
    await repository.persist_connector_result(
        run.id,
        ConnectorResult(
            connector="contract-test",
            connector_version="test-only",
            status=ConnectorRunStatus.SUCCESS,
            profiles=[
                CandidateProfile(
                    platform="github", canonical_url="https://github.com/first", username="first"
                )
            ],
        ),
    )
    snapshots = await repository.list_profile_snapshots_for_search(second.id)
    assert snapshots[0].bio is None
    assert len(snapshots) == 1
