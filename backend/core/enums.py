"""String-valued domain enums shared by persistence, services, and API schemas."""

from enum import StrEnum


class SearchStatus(StrEnum):
    CREATED = "CREATED"
    DISCOVERING = "DISCOVERING"
    NORMALIZING = "NORMALIZING"
    EXPANDING = "EXPANDING"
    ENRICHING = "ENRICHING"
    CORRELATING = "CORRELATING"
    AWAITING_USER = "AWAITING_USER"
    CONTINUING = "CONTINUING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SearchScope(StrEnum):
    SELF_AUDIT = "self_audit"
    CONSENTED = "consented"
    PUBLIC_FIGURE = "public_figure"


class SeedType(StrEnum):
    USERNAME = "USERNAME"
    NAME = "NAME"
    PROFILE_URL = "PROFILE_URL"
    IMAGE = "IMAGE"
    EMAIL = "EMAIL"
    PHONE = "PHONE"


class ConnectorStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    NO_RESULTS = "NO_RESULTS"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"
    FAILED = "FAILED"


class EvidenceDirection(StrEnum):
    SUPPORT = "SUPPORT"
    CONTRADICT = "CONTRADICT"
    NEUTRAL = "NEUTRAL"


class Classification(StrEnum):
    STRONG = "STRONG"
    LIKELY = "LIKELY"
    AMBIGUOUS = "AMBIGUOUS"
    WEAK = "WEAK"
    CONTRADICTORY = "CONTRADICTORY"


class HypothesisStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class QuestionType(StrEnum):
    TEXT = "TEXT"
    YES_NO = "YES_NO"
    SINGLE_SELECT = "SINGLE_SELECT"
    MULTI_SELECT = "MULTI_SELECT"


class QuestionStatus(StrEnum):
    PENDING = "PENDING"
    ANSWERED = "ANSWERED"
    SKIPPED = "SKIPPED"
    EXPIRED = "EXPIRED"


class SensitivityLevel(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ImageEmbeddingType(StrEnum):
    GENERAL_IMAGE = "GENERAL_IMAGE"
    FACE = "FACE"


# Compatibility aliases make intent explicit without creating duplicate enum types.
MatchClassification = Classification
ConnectorRunStatus = ConnectorStatus
EmbeddingType = ImageEmbeddingType


__all__ = [
    "Classification",
    "ConnectorRunStatus",
    "ConnectorStatus",
    "EmbeddingType",
    "EvidenceDirection",
    "HypothesisStatus",
    "ImageEmbeddingType",
    "MatchClassification",
    "QuestionStatus",
    "QuestionType",
    "SearchScope",
    "SearchStatus",
    "SeedType",
    "SensitivityLevel",
]
