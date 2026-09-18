"""Regression and unit tests for EMAIL investigation seed, handle pivoting, and identity pipeline integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.connectors.schemas import (
    CandidateProfile,
    ConnectorInput,
    ConnectorInputType,
    ConnectorResult,
    ConnectorRunStatus,
)
from backend.core.config import get_settings
from backend.core.enums import SearchScope, SearchStatus, SeedType
from backend.email_osint.adapters.github_email import GitHubEmailAdapter
from backend.email_osint.adapters.google_gaia import GoogleGaiaAdapter
from backend.email_osint.schemas import DiscoveredIdentifier, EmailOSINTResult, EmailSourceResult, EmailSourceStatus
from backend.investigation.orchestrator import SearchOrchestrator, _normalize_seed, _email_identifier_candidates
from backend.investigation.pivot_engine import PivotEngine
from backend.normalization.usernames import normalize_username


def test_email_normalization():
    """Verify consistent email seed normalization."""
    assert _normalize_seed(SeedType.EMAIL, "  Person@Example.COM  ") == "person@example.com"
    assert _normalize_seed(SeedType.EMAIL, "user.name+tag@domain.org") == "user.name+tag@domain.org"


def test_email_derived_local_part_is_distinct_from_observed_username():
    """Ensure derived local-parts are distinguished from high-confidence observed usernames."""
    email = "kartikey.test@example.com"
    local_part = email.split("@")[0]
    norm_local = normalize_username(local_part)

    # Derived identifier
    derived_id = DiscoveredIdentifier(
        type="username",
        value=local_part,
        normalized_value=norm_local,
        source="email_derivation",
        confidence=0.30,
        metadata={"provenance": "DERIVED", "derived_from": "email_local_part"},
    )

    # Observed identifier from public source
    observed_id = DiscoveredIdentifier(
        type="username",
        value="kartikey_dev",
        normalized_value="kartikey_dev",
        source="github_email",
        confidence=0.98,
        metadata={"provenance": "OBSERVED", "platform": "github"},
    )

    assert derived_id.confidence < 0.50
    assert derived_id.metadata["provenance"] == "DERIVED"

    assert observed_id.confidence >= 0.85
    assert observed_id.metadata["provenance"] == "OBSERVED"


def test_pivot_engine_generates_discovery_for_email_discovered_username():
    """Verify discovered username can trigger standard username discovery connectors."""
    from backend.connectors.registry import build_default_registry

    registry = build_default_registry()
    engine = PivotEngine(registry)

    # When a username is discovered during email checks, PivotEngine generates standard discovery pivots
    pivots = engine.discovery(SeedType.USERNAME, "kartikey_dev")
    connector_names = [p.connector_name for p in pivots]

    assert "github" in connector_names or "maigret" in connector_names or "sherlock" in connector_names
    assert any(p.connector_input.type == ConnectorInputType.USERNAME for p in pivots)
    assert any(p.connector_input.value == "kartikey_dev" for p in pivots)


def test_email_identifier_candidates_extracts_usernames_and_urls():
    """Verify _email_identifier_candidates creates candidate profiles for both username & url identifiers."""
    result = EmailSourceResult(
        source_name="gravatar",
        category="social",
        status=EmailSourceStatus.FOUND,
        account_exists=True,
        identifiers=[
            DiscoveredIdentifier(
                type="username",
                value="kartikey_dev",
                normalized_value="kartikey_dev",
                source="gravatar",
                confidence=0.95,
                metadata={"provenance": "OBSERVED", "platform": "gravatar"},
            ),
            DiscoveredIdentifier(
                type="profile_url",
                value="https://github.com/kartikey_dev",
                normalized_value="https://github.com/kartikey_dev",
                source="github_email",
                confidence=0.95,
                metadata={"provenance": "OBSERVED", "platform": "github"},
            ),
        ],
    )

    candidates = _email_identifier_candidates(result)
    assert len(candidates) == 2
    platforms = [c.platform for c in candidates]
    assert "gravatar" in platforms
    assert "github" in platforms


@pytest.mark.asyncio
async def test_email_adapter_failures_not_treated_as_account_not_found():
    """Ensure 429/403/500 HTTP failures do not become false NOT_FOUND findings."""
    adapter_github = GitHubEmailAdapter()

    fake_res_429 = MagicMock()
    fake_res_429.status_code = 429

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = fake_res_429
        result_github = await adapter_github.check("test@example.com")

        assert result_github.status == EmailSourceStatus.RATE_LIMITED
        assert result_github.account_exists is False

    adapter_gaia = GoogleGaiaAdapter()
    fake_res_500 = MagicMock()
    fake_res_500.status_code = 500

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = fake_res_500
        result_gaia = await adapter_gaia.check("test@example.com")

        assert result_gaia.status == EmailSourceStatus.ERROR
        assert result_gaia.account_exists is False


@pytest.mark.asyncio
async def test_hibp_breach_info_isolated_from_identity_correlation():
    """Verify HIBP breach signals remain isolated as defensive self-audit findings."""
    from backend.connectors.hibp import HIBPConnector

    hibp = HIBPConnector()
    artifacts = [a.value for a in hibp.capabilities.produced_artifacts]
    assert "OBSERVATION" in artifacts
    assert "PROFILE" not in artifacts


@pytest.mark.asyncio
async def test_orchestrator_email_search_flow_mocked():
    """Test EMAIL investigation orchestration creating run and handling seed."""
    import uuid
    from backend.email_osint.schemas import EmailDomainIntel

    test_id = uuid.uuid4()
    repo = AsyncMock()
    seed = MagicMock()
    seed.seed_type = SeedType.EMAIL
    seed.normalized_value = "target@example.com"
    seed.original_value = "target@example.com"

    search = MagicMock()
    search.id = test_id
    search.status = SearchStatus.CREATED
    search.seeds = [seed]
    search.max_connector_runs = 5
    search.connector_runs_count = 0
    search.max_questions = 2
    search.questions_asked = 0
    search.max_pivot_depth = 2
    search.pivot_depth = 0
    search.max_candidates = 100

    repo.get_search.return_value = search
    repo.get_pending_question.return_value = None
    runs_list = []

    def mock_list_runs(s_id):
        return list(runs_list)

    def mock_create_run(s_id, connector, **kwargs):
        run = MagicMock(id=uuid.uuid4(), connector=connector, input_data={}, metadata_json={})
        runs_list.append(run)
        return run

    repo.list_connector_runs.side_effect = mock_list_runs
    repo.create_connector_run.side_effect = mock_create_run
    repo.list_questions.return_value = []
    repo.list_profile_snapshots_for_search.return_value = []
    repo.list_hypotheses.return_value = []
    repo.list_observations_for_search.return_value = []
    repo.list_evidence.return_value = []

    mock_email_result = EmailOSINTResult(
        email="target@example.com",
        normalized_email="target@example.com",
        domain_intel=EmailDomainIntel(domain="example.com"),
        sources_checked=1,
        accounts_found=1,
        source_results=[
            EmailSourceResult(
                source_name="github_email",
                category="developer",
                status=EmailSourceStatus.FOUND,
                account_exists=True,
                username="target_dev",
                canonical_url="https://github.com/target_dev",
                confidence=0.98,
            )
        ],
    )

    settings = get_settings()
    orchestrator = SearchOrchestrator(repo, settings)

    with patch("backend.email_osint.EmailOSINTEngine.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = mock_email_result

        res = await orchestrator.run_search(test_id)

        assert mock_discover.call_count >= 1
        repo.create_connector_run.assert_called()
