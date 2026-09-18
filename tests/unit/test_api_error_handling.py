"""Regression tests for structured API error handling and idempotent continuation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from backend import jobs
from backend.app.main import app, unhandled_exception_handler
from backend.core.enums import SearchStatus


def _request(path: str = "/api/searches") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
    )


@pytest.mark.asyncio
async def test_unhandled_exception_handler_returns_machine_readable_body():
    response = await unhandled_exception_handler(_request(), RuntimeError("boom"))

    assert response.status_code == 500
    payload = json.loads(response.body)
    assert payload["detail"] == "Internal Server Error"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error"] == "boom"


def test_api_returns_structured_500_instead_of_plain_internal_server_error(monkeypatch):
    """The frontend parses JSON; a bare ``Internal Server Error`` body breaks it."""

    def boom():
        raise RuntimeError("registry exploded")

    monkeypatch.setattr("backend.app.main.build_default_registry", boom)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/connectors")

    assert response.status_code == 500
    payload = response.json()
    assert payload["error_type"] == "RuntimeError"
    assert "registry exploded" in payload["error"]


@pytest.mark.asyncio
async def test_continue_search_is_idempotent_when_an_answer_already_advanced_it(monkeypatch):
    """Auto-continue can race a manual answer; that must not surface as a 500."""

    search = MagicMock()
    search.id = uuid4()
    search.status = SearchStatus.AWAITING_USER

    async def fake_lock(session, search_id):  # noqa: ARG001 - mirrors jobs.lock_search signature
        return search

    async def fake_submit(*args, **kwargs):  # noqa: ARG001 - mirrors jobs.submit_answer signature
        raise ValueError("Search is not awaiting an answer.")

    monkeypatch.setattr(jobs, "lock_search", fake_lock)
    monkeypatch.setattr(jobs, "submit_answer", fake_submit)

    repository = AsyncMock()
    repository.session = MagicMock()
    repository.get_pending_question.return_value = MagicMock()
    repository.get_search.return_value = search

    assert await jobs.continue_search(repository, search.id) is search