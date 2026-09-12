"""Database metadata checks that do not require a running PostgreSQL instance."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from backend.core.config import IMAGE_EMBEDDING_DIMENSION, TEXT_EMBEDDING_DIMENSION
from backend.core.enums import EvidenceDirection, SearchScope, SearchStatus
from backend.db.models import (
    Base,
    EvidenceSignal,
    IdentityHypothesis,
    ImageEmbedding,
    Profile,
    SearchRun,
    TextEmbedding,
)

EXPECTED_TABLES = {
    "search_events",
    "user_search_context",
    "investigation_jobs",
    "connector_runs",
    "evidence_signals",
    "hypothesis_memberships",
    "identifiers",
    "identity_hypotheses",
    "face_instances",
    "image_artifacts",
    "image_embeddings",
    "investigation_answers",
    "investigation_questions",
    "profile_identifiers",
    "profile_observations",
    "profile_relationships",
    "profiles",
    "reports",
    "search_runs",
    "search_seeds",
    "text_embeddings",
}


def test_all_required_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_profile_has_both_canonical_uniqueness_strategies() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in Profile.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("platform", "platform_account_id") in unique_columns
    assert ("platform", "canonical_url") in unique_columns


def test_provenance_payloads_use_jsonb_and_uuid_arrays() -> None:
    assert isinstance(EvidenceSignal.__table__.c.raw_value.type, JSONB)
    source_ids = EvidenceSignal.__table__.c.source_observation_ids.type
    assert isinstance(source_ids, ARRAY)
    assert source_ids.item_type.as_uuid is True


def test_embedding_dimensions_are_explicit_without_premature_indexes() -> None:
    text_vector = TextEmbedding.__table__.c.embedding.type
    image_vector = ImageEmbedding.__table__.c.embedding.type

    assert isinstance(text_vector, Vector)
    assert isinstance(image_vector, Vector)
    assert text_vector.dim == TEXT_EMBEDDING_DIMENSION
    assert image_vector.dim == IMAGE_EMBEDDING_DIMENSION
    assert not any("hnsw" in index.name.lower() for index in TextEmbedding.__table__.indexes)
    assert not any("hnsw" in index.name.lower() for index in ImageEmbedding.__table__.indexes)


def test_public_enum_values_are_stable_strings() -> None:
    assert SearchStatus.AWAITING_USER.value == "AWAITING_USER"
    assert SearchScope.SELF_AUDIT.value == "self_audit"
    assert EvidenceDirection.CONTRADICT.value == "CONTRADICT"


def test_search_scope_limits_and_hypothesis_rank_are_persisted() -> None:
    assert {"scope", "max_candidates", "max_search_duration_seconds"} <= {
        column.name for column in SearchRun.__table__.columns
    }
    assert "rank" in IdentityHypothesis.__table__.columns
