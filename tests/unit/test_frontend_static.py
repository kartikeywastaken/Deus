"""Tests for frontend static file serving and Task 3 UI contract elements."""

import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_index_html_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "DEUS" in response.text


def test_task3_ui_elements_exist():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # 1. Passive Audit Stream Section
    assert 'id="stage2-fingerprint"' in html
    assert 'id="fingerprint-signals"' in html

    # 2. Target Entry
    assert 'id="search-panel-section"' in html
    assert 'id="seed-type"' in html
    assert 'id="seed"' in html
    assert 'Start investigation' in html

    # 3. Lookup Tool & Recon Metrics
    assert 'id="stage3-lookup-tool"' in html
    assert 'id="metrics-section"' in html
    assert 'id="candidate-count"' in html
    assert 'id="evidence-count"' in html
    assert 'id="run-count"' in html

    # 4. Account Discovery
    assert 'id="view-overview"' in html
    assert 'id="candidates"' in html

    # 5. OSINT Identity Sections
    assert 'id="email-osint-section"' in html

    # 6. Investigation Report Section
    assert 'id="view-report"' in html
    assert 'id="report"' in html

    # 7. Removed Legacy Sections
    assert 'id="view-graph-section"' not in html
    assert 'id="view-contradictions-section"' not in html
    assert 'id="view-hypotheses-section"' not in html

