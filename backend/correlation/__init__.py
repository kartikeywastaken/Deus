"""Pure entity-resolution primitives.

The package intentionally knows nothing about PostgreSQL, SQLAlchemy, FastAPI,
or connector implementations. Callers translate persisted profiles into
``NormalizedProfile`` records and persist returned assessments separately.
"""

from .candidate_generation import CandidatePair, generate_candidate_pairs
from .clustering import build_identity_hypotheses
from .engine import CorrelationResult, correlate_profiles
from .features import (
    BlockingReason,
    Classification,
    Direction,
    EvidenceContribution,
    EvidenceFamily,
    EvidenceSignal,
    IdentityHypothesis,
    IdentityMembership,
    PairAssessment,
    SignalType,
)
from .scorer import CorrelationScorer, score_evidence

__all__ = [
    "BlockingReason",
    "CandidatePair",
    "Classification",
    "CorrelationScorer",
    "CorrelationResult",
    "Direction",
    "EvidenceContribution",
    "EvidenceFamily",
    "EvidenceSignal",
    "IdentityHypothesis",
    "IdentityMembership",
    "PairAssessment",
    "SignalType",
    "build_identity_hypotheses",
    "correlate_profiles",
    "generate_candidate_pairs",
    "score_evidence",
]
