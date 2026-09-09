"""Abstract base class and metadata for Email OSINT source adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .schemas import EmailSourceResult, EmailSourceStatus


class BaseEmailSource(ABC):
    """Common interface for all Email OSINT source adapters."""

    name: str
    category: str = "general"
    cost: int = 1  # 1 = cheap/fast, 5 = expensive/slow
    expected_latency_ms: int = 500
    reliability: float = 0.9
    rate_limit_per_min: int = 60
    priority: int = 50  # Lower number = higher priority

    @abstractmethod
    async def check(self, email: str, context: dict[str, Any] | None = None) -> EmailSourceResult:
        """Perform a passive, non-intrusive lookup for the given email address."""

    def _result(
        self,
        status: EmailSourceStatus,
        *,
        account_exists: bool = False,
        canonical_url: str | None = None,
        display_name: str | None = None,
        username: str | None = None,
        avatar_url: str | None = None,
        confidence: float = 0.5,
        identifiers: list[Any] | None = None,
        evidence: dict[str, Any] | None = None,
        response_time_ms: float = 0.0,
        message: str | None = None,
    ) -> EmailSourceResult:
        return EmailSourceResult(
            source_name=self.name,
            category=self.category,
            status=status,
            account_exists=account_exists,
            canonical_url=canonical_url,
            display_name=display_name,
            username=username,
            avatar_url=avatar_url,
            confidence=confidence,
            identifiers=identifiers or [],
            evidence=evidence or {},
            response_time_ms=response_time_ms,
            message=message,
        )
