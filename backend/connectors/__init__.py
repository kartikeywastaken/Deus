"""Public connector framework exports."""

from .base import (
    BaseConnector,
    Connector,
    ConnectorNormalizationError,
)
from .gitfive import GitFiveConnector
from .maigret import MaigretConnector
from .registry import (
    ConnectorRegistry,
    DuplicateConnectorError,
    UnknownConnectorError,
    build_default_registry,
)
from .schemas import (
    CandidateProfile,
    ConnectorAvailability,
    ConnectorCapabilities,
    ConnectorInput,
    ConnectorInputType,
    ConnectorMode,
    ConnectorResult,
    ConnectorRunStatus,
    IdentifierArtifact,
    IdentifierType,
    ObservationArtifact,
    ProducedArtifactType,
    RelationshipArtifact,
)
from .sherlock import SherlockConnector
from .social_analyzer import SocialAnalyzerConnector
from .sylva import SylvaConnector

__all__ = [
    "BaseConnector",
    "CandidateProfile",
    "Connector",
    "ConnectorAvailability",
    "ConnectorCapabilities",
    "ConnectorInput",
    "ConnectorInputType",
    "ConnectorMode",
    "ConnectorNormalizationError",
    "ConnectorRegistry",
    "ConnectorResult",
    "ConnectorRunStatus",
    "DuplicateConnectorError",
    "GitFiveConnector",
    "IdentifierArtifact",
    "IdentifierType",
    "MaigretConnector",
    "ObservationArtifact",
    "ProducedArtifactType",
    "RelationshipArtifact",
    "SherlockConnector",
    "SocialAnalyzerConnector",
    "SylvaConnector",
    "UnknownConnectorError",
    "build_default_registry",
]
