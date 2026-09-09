"""Identity Graph builder for Email OSINT evidence correlation."""

from __future__ import annotations

from typing import Any

from .schemas import (
    DiscoveredIdentifier,
    EmailSourceResult,
    GraphEdge,
    GraphNode,
    IdentityGraphData,
)


class IdentityGraphBuilder:
    """Constructs a deterministic identity graph from email OSINT discoveries."""

    def __init__(self, seed_email: str) -> None:
        self.seed_email = seed_email.strip().lower()
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._added_edges: set[tuple[str, str, str]] = set()

        # Add seed email node
        email_node_id = f"email:{self.seed_email}"
        self._nodes[email_node_id] = GraphNode(
            id=email_node_id,
            label=self.seed_email,
            type="email",
            confidence=1.0,
        )

    def add_domain_intel(self, domain: str, provider_name: str, org_hint: str | None = None) -> None:
        email_node_id = f"email:{self.seed_email}"
        domain_node_id = f"domain:{domain}"

        if domain_node_id not in self._nodes:
            self._nodes[domain_node_id] = GraphNode(
                id=domain_node_id,
                label=domain,
                type="domain",
                metadata={"provider": provider_name},
                confidence=0.99,
            )

        self._add_edge(email_node_id, domain_node_id, "USES_DOMAIN", confidence=0.99, source="domain_intel")

        if org_hint:
            org_node_id = f"org:{org_hint.casefold()}"
            if org_node_id not in self._nodes:
                self._nodes[org_node_id] = GraphNode(
                    id=org_node_id,
                    label=org_hint,
                    type="organization",
                    confidence=0.7,
                )
            self._add_edge(domain_node_id, org_node_id, "HOSTED_BY", confidence=0.75, source="domain_intel")

    def add_source_result(self, result: EmailSourceResult) -> None:
        if not result.account_exists:
            return

        email_node_id = f"email:{self.seed_email}"
        account_id = f"account:{result.source_name.casefold()}"

        label = result.username or result.display_name or result.source_name
        self._nodes[account_id] = GraphNode(
            id=account_id,
            label=f"{result.source_name}: {label}",
            type="account",
            platform=result.source_name,
            confidence=result.confidence,
            metadata={"canonical_url": result.canonical_url, "avatar_url": result.avatar_url},
        )

        self._add_edge(
            email_node_id,
            account_id,
            "REGISTERED_ON",
            confidence=result.confidence,
            source=result.source_name,
        )

        # Process extracted identifiers
        for identifier in result.identifiers:
            self.add_identifier(identifier, parent_node_id=account_id)

    def add_identifier(self, identifier: DiscoveredIdentifier, parent_node_id: str | None = None) -> None:
        node_id = f"{identifier.type}:{identifier.normalized_value}"
        if node_id not in self._nodes:
            self._nodes[node_id] = GraphNode(
                id=node_id,
                label=identifier.value,
                type=identifier.type,
                confidence=identifier.confidence,
            )

        source_node = parent_node_id or f"email:{self.seed_email}"
        rel_type = "ASSOCIATED_WITH" if identifier.type == "username" else "LINKS_TO"
        self._add_edge(source_node, node_id, rel_type, confidence=identifier.confidence, source=identifier.source)

    def _add_edge(self, source_node: str, target: str, relationship: str, confidence: float = 1.0, source: str | None = None) -> None:
        if source_node == target:
            return
        key = (source_node, target, relationship)
        if key not in self._added_edges:
            self._added_edges.add(key)
            self._edges.append(
                GraphEdge(
                    source=source_node,
                    target=target,
                    relationship=relationship,
                    confidence=confidence,
                    source_name=source,
                )
            )

    def build(self) -> IdentityGraphData:
        return IdentityGraphData(
            nodes=list(self._nodes.values()),
            edges=self._edges,
        )
