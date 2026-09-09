"""Email OSINT & Identity Discovery Engine package."""

from .engine import EmailOSINTEngine
from .schemas import (
    DiscoveredIdentifier,
    EmailDomainIntel,
    EmailOSINTResult,
    EmailSourceResult,
    EmailSourceStatus,
)

__all__ = [
    "DiscoveredIdentifier",
    "EmailDomainIntel",
    "EmailOSINTEngine",
    "EmailOSINTResult",
    "EmailSourceResult",
    "EmailSourceStatus",
]
