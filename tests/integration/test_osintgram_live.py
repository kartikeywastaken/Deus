"""Real operator-configured lookup only; never substitute a saved network response."""

import os

import pytest

from backend.connectors import ConnectorInput, ConnectorInputType
from backend.connectors.osintgram import OsintgramConnector


@pytest.mark.live
async def test_osintgram_public_profile_with_operator_session():
    username = os.getenv("DEUS_TEST_INSTAGRAM_USERNAME")
    connector = OsintgramConnector()
    if not username or connector.availability.value != "AVAILABLE":
        pytest.skip("Osintgram needs an explicit operator session and controlled public username")
    result = await connector.discover(
        ConnectorInput(
            type=ConnectorInputType.INSTAGRAM_PROFILE,
            value=f"https://instagram.com/{username}",
        )
    )
    assert result.status.value == "SUCCESS", f"{result.status}: {result.message}"
    assert result.request_count == 1
    assert result.profiles[0].username.casefold() == username.casefold()
    assert result.profiles[0].raw["is_private"] is False
    assert (
        not {"public_email", "phone_number", "contact_phone_number"} & result.profiles[0].raw.keys()
    )
