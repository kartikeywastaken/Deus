"""PostgreSQL persistence boundary for investigations."""

from .postgres import (
    InvalidRepositoryState,
    PostgresInvestigationRepository,
    RepositoryEntityNotFound,
    evidence_key,
)
from .protocol import InvestigationRepository
from .types import (
    PersistedConnectorResult,
    ProfileSnapshot,
    QuestionAnswerResult,
    SearchLimits,
)

__all__ = [
    "InvalidRepositoryState",
    "InvestigationRepository",
    "PersistedConnectorResult",
    "PostgresInvestigationRepository",
    "ProfileSnapshot",
    "QuestionAnswerResult",
    "RepositoryEntityNotFound",
    "SearchLimits",
    "evidence_key",
]
