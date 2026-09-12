"""Offline contract checks; never execute or simulate collection."""

import pytest

from backend.connectors import (
    Connector,
    ConnectorMode,
    DuplicateConnectorError,
    build_default_registry,
)


def test_registry_is_live_only():
    registry = build_default_registry()
    assert all(isinstance(c, Connector) for c in registry)
    assert all(c.mode == ConnectorMode.LIVE for c in registry)
    with pytest.raises(ValueError):
        ConnectorMode("MOCK")
    with pytest.raises(DuplicateConnectorError):
        registry.register(registry.get("github"))


async def test_manual_connectors_never_invent_results():
    from backend.connectors import ConnectorInput, ConnectorInputType

    registry = build_default_registry()
    for name in ("sylva", "gitfive"):
        result = await registry.get(name).discover(
            ConnectorInput(type=ConnectorInputType.USERNAME, value="input-only")
        )
        assert result.status in {"MANUAL", "DISABLED", "NO_RESULTS"}
        assert not result.profiles
        assert result.request_count == 0
