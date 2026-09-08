"""Public connector framework exports."""

from .base import (
    BaseConnector,
    Connector,
    ConnectorNormalizationError,
)
from .gitfive import GitFiveConnector, MockGitFiveConnector
from .maigret import MaigretConnector, MockMaigretConnector
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
from .sherlock import MockSherlockConnector, SherlockConnector
from .social_analyzer import MockSocialAnalyzerConnector, SocialAnalyzerConnector
from .sylva import MockSylvaConnector, SylvaConnector

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
    "MockGitFiveConnector",
    "MockMaigretConnector",
    "MockSherlockConnector",
    "MockSocialAnalyzerConnector",
    "MockSylvaConnector",
    "ObservationArtifact",
    "ProducedArtifactType",
    "RelationshipArtifact",
    "SherlockConnector",
    "SocialAnalyzerConnector",
    "SylvaConnector",
    "UnknownConnectorError",
    "build_default_registry",
]
