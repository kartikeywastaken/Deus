"""Capability-driven connector selection with strict loop prevention."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.connectors import CandidateProfile, ConnectorInput, ConnectorInputType
from backend.connectors.registry import ConnectorRegistry
from backend.core.enums import SeedType
from backend.normalization.urls import canonicalize_url
from backend.normalization.usernames import normalize_username


@dataclass(frozen=True, slots=True)
class Pivot:
    """One connector invocation selected from a newly available artifact."""

    connector_name: str
    connector_input: ConnectorInput
    stage: str
    priority: int

    @property
    def fingerprint(self) -> str:
        normalized = self.connector_input.value.strip().casefold()
        if self.connector_input.type in {
            ConnectorInputType.PROFILE,
            ConnectorInputType.PROFILE_URL,
            ConnectorInputType.GITHUB_PROFILE,
            ConnectorInputType.INSTAGRAM_PROFILE,
        }:
            try:
                normalized = canonicalize_url(normalized)
            except ValueError:
                pass
        elif self.connector_input.type is ConnectorInputType.USERNAME:
            normalized = normalize_username(normalized)
        return f"{self.connector_name.casefold()}:{self.connector_input.type.value}:{normalized}"


@dataclass(slots=True)
class PivotLedger:
    """In-memory loop guard; connector runs remain persisted separately."""

    fingerprints: set[str] = field(default_factory=set)

    def unseen(self, pivot: Pivot) -> bool:
        return pivot.fingerprint not in self.fingerprints

    def claim(self, pivot: Pivot) -> bool:
        if not self.unseen(pivot):
            return False
        self.fingerprints.add(pivot.fingerprint)
        return True


class PivotEngine:
    """Select only connectors whose declared inputs match current artifacts."""

    _SEED_INPUTS = {
        SeedType.USERNAME: ConnectorInputType.USERNAME,
        SeedType.NAME: ConnectorInputType.NAME,
        SeedType.PROFILE_URL: ConnectorInputType.PROFILE_URL,
        SeedType.IMAGE: ConnectorInputType.IMAGE,
        SeedType.EMAIL: ConnectorInputType.EMAIL,
        SeedType.PHONE: ConnectorInputType.PHONE,
    }
    _DISCOVERY_PRIORITY = {"github": 5, "github_search": 8, "maigret": 10, "sherlock": 20}

    def __init__(self, registry: ConnectorRegistry) -> None:
        self.registry = registry

    def discovery(self, seed_type: SeedType, value: str) -> tuple[Pivot, ...]:
        input_type = self._SEED_INPUTS[seed_type]
        pivots = [
            Pivot(
                connector_name=connector.name,
                connector_input=ConnectorInput(type=input_type, value=value),
                stage="DISCOVERING",
                priority=self._DISCOVERY_PRIORITY.get(connector.name, 100),
            )
            for connector in self.registry.eligible_for(input_type, discovery_only=True)
            if connector.name in self._DISCOVERY_PRIORITY
        ]
        return tuple(sorted(pivots, key=lambda item: (item.priority, item.connector_name)))

    def expansion(self, usernames: list[str]) -> tuple[Pivot, ...]:
        try:
            self.registry.get("sylva")
        except KeyError:
            return ()
        pivots: list[Pivot] = []
        for username in dict.fromkeys(normalize_username(value) for value in usernames):
            if username:
                pivots.append(
                    Pivot(
                        connector_name="sylva",
                        connector_input=ConnectorInput(
                            type=ConnectorInputType.USERNAME,
                            value=username,
                        ),
                        stage="EXPANDING",
                        priority=30,
                    )
                )
        return tuple(pivots)

    def enrichment(self, profiles: list[CandidateProfile]) -> tuple[Pivot, ...]:
        pivots: list[Pivot] = []
        for profile in profiles:
            try:
                self.registry.get("social_analyzer")
            except KeyError:
                pass
            else:
                pivots.append(
                    Pivot(
                        connector_name="social_analyzer",
                        connector_input=ConnectorInput(
                            type=ConnectorInputType.PROFILE,
                            value=profile.canonical_url,
                            profile=profile,
                        ),
                        stage="ENRICHING",
                        priority=40,
                    )
                )

            if profile.platform.casefold() == "github":
                try:
                    self.registry.get("gitfive")
                except KeyError:
                    continue
                pivots.append(
                    Pivot(
                        connector_name="gitfive",
                        connector_input=ConnectorInput(
                            type=ConnectorInputType.GITHUB_PROFILE,
                            value=profile.canonical_url,
                            profile=profile,
                        ),
                        stage="ENRICHING",
                        priority=50,
                    )
                )
        return tuple(sorted(pivots, key=lambda item: (item.priority, item.fingerprint)))

    @staticmethod
    def claim_within_limit(
        pivots: tuple[Pivot, ...],
        ledger: PivotLedger,
        remaining_runs: int,
    ) -> tuple[Pivot, ...]:
        selected: list[Pivot] = []
        for pivot in pivots:
            if len(selected) >= max(0, remaining_runs):
                break
            if ledger.claim(pivot):
                selected.append(pivot)
        return tuple(selected)
