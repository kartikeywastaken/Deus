"""High-performance Email OSINT & Identity Discovery Engine orchestrator."""

from __future__ import annotations

import time
from typing import Any, Callable

from .correlation import EmailCorrelationEngine
from .executor import EmailTaskExecutor
from .graph import IdentityGraphBuilder
from .registry import EmailSourceRegistry, build_default_email_registry
from .schemas import (
    DiscoveredIdentifier,
    EmailDomainIntel,
    EmailOSINTResult,
    EmailSourceResult,
)


class EmailOSINTEngine:
    """Orchestrates parallel discovery, identifier extraction, domain intel, and identity graph building."""

    def __init__(
        self,
        registry: EmailSourceRegistry | None = None,
        executor: EmailTaskExecutor | None = None,
    ) -> None:
        self.registry = registry or build_default_email_registry()
        self.executor = executor or EmailTaskExecutor(self.registry)

    async def discover(
        self,
        email: str,
        *,
        context: dict[str, Any] | None = None,
        event_callback: Callable[[EmailSourceResult], Any] | None = None,
    ) -> EmailOSINTResult:
        """Run complete email intelligence flow starting from an email seed."""

        start_time = time.monotonic()
        normalized_email = email.strip().lower()

        # 1. Execute source adapters concurrently
        results = await self.executor.execute_all(
            normalized_email,
            context=context,
            event_callback=event_callback,
        )

        # 2. Extract and deduplicate all discovered identifiers
        all_identifiers: list[DiscoveredIdentifier] = []
        domain_intel = None

        for res in results:
            if res.identifiers:
                all_identifiers.extend(res.identifiers)
            if res.source_name == "domain_intel" and res.evidence:
                domain_intel = EmailDomainIntel.model_validate(res.evidence)

        if domain_intel is None:
            domain = normalized_email.split("@")[-1] if "@" in normalized_email else "unknown"
            domain_intel = EmailDomainIntel(domain=domain)

        deduped_identifiers = EmailCorrelationEngine.deduplicate_identifiers(all_identifiers)

        # 3. Calculate calibrated confidence score
        confidence = EmailCorrelationEngine.calculate_overall_confidence(results, deduped_identifiers)

        # 4. Construct Identity Graph
        graph_builder = IdentityGraphBuilder(normalized_email)
        graph_builder.add_domain_intel(
            domain=domain_intel.domain,
            provider_name=domain_intel.provider_name,
            org_hint=domain_intel.organization_hint,
        )

        for res in results:
            graph_builder.add_source_result(res)

        identity_graph = graph_builder.build()
        duration_ms = (time.monotonic() - start_time) * 1000

        accounts_found = sum(1 for r in results if r.account_exists)

        return EmailOSINTResult(
            email=email,
            normalized_email=normalized_email,
            domain_intel=domain_intel,
            sources_checked=len(results),
            accounts_found=accounts_found,
            source_results=results,
            discovered_identifiers=deduped_identifiers,
            pivoted_profiles=[],
            identity_graph=identity_graph,
            overall_confidence=confidence,
            scan_duration_ms=duration_ms,
        )
