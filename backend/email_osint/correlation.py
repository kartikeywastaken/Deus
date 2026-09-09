"""Correlation and evidence-based confidence scoring for Email OSINT."""

from __future__ import annotations

from typing import Any

from .schemas import DiscoveredIdentifier, EmailSourceResult


class EmailCorrelationEngine:
    """Aggregates evidence and calculates cross-source identity correlation."""

    @staticmethod
    def deduplicate_identifiers(identifiers: list[DiscoveredIdentifier]) -> list[DiscoveredIdentifier]:
        seen: set[tuple[str, str]] = set()
        deduped: list[DiscoveredIdentifier] = []
        for item in identifiers:
            key = (item.type, item.normalized_value)
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped

    @staticmethod
    def calculate_overall_confidence(
        source_results: list[EmailSourceResult],
        discovered_identifiers: list[DiscoveredIdentifier],
    ) -> float:
        """Calculate calibrated confidence score (0.0 to 1.0) based on observable evidence."""
        found_sources = [s for s in source_results if s.account_exists]
        if not found_sources:
            return 0.0

        # Base confidence from highest individual source
        max_base = max((s.confidence for s in found_sources), default=0.0)

        # Bonuses for multiple independent sources matching
        source_count = len(found_sources)
        bonus = min(0.15, (source_count - 1) * 0.05) if source_count > 1 else 0.0

        # Bonus for extracted usernames/profile handles
        usernames = [i for i in discovered_identifiers if i.type == "username"]
        if len(usernames) >= 2:
            bonus += 0.05

        return round(min(1.0, max_base + bonus), 2)

    @staticmethod
    def group_by_handle(source_results: list[EmailSourceResult]) -> dict[str, list[dict[str, Any]]]:
        """Correlate accounts discovered under identical handles/usernames."""
        handle_map: dict[str, list[dict[str, Any]]] = {}
        for s in source_results:
            if s.account_exists and s.username:
                norm_h = s.username.casefold()
                handle_map.setdefault(norm_h, []).append(
                    {
                        "source": s.source_name,
                        "canonical_url": s.canonical_url,
                        "display_name": s.display_name,
                        "confidence": s.confidence,
                    }
                )
        return handle_map
