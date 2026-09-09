"""A real running API/worker and operator-provided seed are required."""

import asyncio
import os

import httpx
import pytest

pytestmark = pytest.mark.live


async def test_live_events_resume_and_cancel():
    base, seed = os.getenv("DEUS_TEST_API_URL"), os.getenv("DEUS_TEST_USERNAME")
    if not base or not seed:
        pytest.skip("Set DEUS_TEST_API_URL and DEUS_TEST_USERNAME for the real worker test")
    async with httpx.AsyncClient(base_url=base, timeout=15) as client:
        response = await client.post("/api/searches", json={"value": seed})
        assert response.status_code == 202
        search_id = response.json()["id"]
        root = f"/api/searches/{search_id}"
        cursor = None
        async with client.stream("GET", root + "/events") as events:
            assert events.headers["content-type"].startswith("text/event-stream")
            async for line in events.aiter_lines():
                if line.startswith("id:"):
                    cursor = int(line.split(":", 1)[1])
                    break
        assert cursor is not None
        await client.post(root + "/stop")
        async with client.stream(
            "GET", root + "/events", headers={"Last-Event-ID": str(cursor)}
        ) as events:
            async for line in events.aiter_lines():
                if line.startswith("id:"):
                    assert int(line.split(":", 1)[1]) > cursor
                if line == "event: done":
                    break
        await asyncio.sleep(2.5)
        assert (await client.get(root)).json()["status"] == "CANCELLED"


@pytest.mark.parametrize("connector", ["ghunt", "hibp"])
async def test_authenticated_self_audit_live(connector):
    from backend.connectors import ConnectorInput, ConnectorInputType, build_default_registry

    seed = os.getenv("DEUS_TEST_EMAIL")
    if not seed:
        pytest.skip("No operator-supplied self-audit email; no fabricated email tests")
    c = build_default_registry().get(connector)
    if c.availability != "AVAILABLE":
        pytest.skip(f"{connector}: {c.availability}")
    result = await c.discover(ConnectorInput(type=ConnectorInputType.EMAIL, value=seed))
    if result.status in {"AUTH_REQUIRED", "RATE_LIMITED", "UNAVAILABLE"}:
        pytest.skip(f"{connector}: {result.status}")
    assert result.status in {"SUCCESS", "PARTIAL", "NO_RESULTS"}, result.message


async def test_gitfive_live():
    from backend.connectors import ConnectorInput, ConnectorInputType, build_default_registry

    seed = os.getenv("DEUS_TEST_USERNAME")
    c = build_default_registry().get("gitfive")
    if not seed or c.availability != "AVAILABLE":
        pytest.skip("GitFive requires operator opt-in and login")
    result = await c.discover(
        ConnectorInput(type=ConnectorInputType.GITHUB_PROFILE, value=f"https://github.com/{seed}")
    )
    if result.status in {"AUTH_REQUIRED", "RATE_LIMITED", "UNAVAILABLE"}:
        pytest.skip(str(result.status))
    assert result.status in {"SUCCESS", "PARTIAL", "NO_RESULTS"}, result.message
