# Deus

Backend-first, Akinator-inspired OSINT identity-correlation engine.

**No simulation. No mock data. No fake fallbacks.**
Every result originates from real live public sources. If a connector fails it reports the real reason (`UNAVAILABLE`, `AUTH_REQUIRED`, `RATE_LIMITED`, `MANUAL`, `FAILED`) and the search continues.

---

## What it does

```
REAL SEED (username / GitHub URL)
  → live discovery (Maigret, Sherlock, GitHub)
  → normalize + deduplicate → PostgreSQL
  → conditional enrichment (Social Analyzer, website parser)
  → pairwise evidence extraction (username, name, domain, bio vectors, links)
  → correlation engine → competing identity hypotheses
  → Akinator: ask one targeted question only if it materially separates candidates
  → resume live search with user hint
  → deterministic stopping rules
  → explainable ranked report
```

Matching usernames are **candidates**, not proof of shared identity.
Scores are not probabilities until calibrated.

---

## Quick start

```bash
# 1. PostgreSQL + pgvector
docker compose up -d

# 2. Python environment
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[live]"

# 3. Copy config
cp .env.example .env   # edit DATABASE_URL if needed

# 4. Database migrations
alembic upgrade head

# 5. Start worker (separate terminal)
python -m backend.worker

# 6. Start API
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765

# 7. Open UI
open http://127.0.0.1:8765/
```

---

## System health

```bash
# JSON report: connectors, DB, migrations, job queue
python -m backend.doctor

# Human-readable dependency check
python scripts/check_dependencies.py

# Live integration tests (uses real internet)
DEUS_TEST_USERNAME=<your-github-handle> pytest -m live

# All deterministic unit tests
pytest
```

---

## Connector matrix

| Connector | Status | Auth | Notes |
|-----------|--------|------|-------|
| Maigret 0.6.5 | AVAILABLE | No | 20-platform live subprocess; CSV parsing |
| Sherlock 0.16.0 | AVAILABLE | No | Full local site DB; CSV parsing |
| GitHub REST | AVAILABLE | Optional token | Stable user ID, bio, social links, avatar |
| GitHub Search | AVAILABLE | Optional token | Name/username search |
| Social Analyzer 0.45 | AVAILABLE | No | Enriches discovered GitHub/Reddit profiles |
| Website parser | AVAILABLE | No | Single-page bounded link extraction; SSRF-protected |
| Sylva | MANUAL | No | `operator_reviewed_config` — automatic execution not enabled |
| GitFive | MANUAL | Yes | Requires operator login; interactive |
| GHunt | AUTH_REQUIRED | Yes (cookies) | No unattended cookie adapter configured |
| OSINTgram | AUTH_REQUIRED | Yes (Instagram) | No authenticated adapter |
| InstagramOSINT | UNAVAILABLE | — | Upstream archived |
| LinkedInt | MANUAL | — | No current legitimate unattended integration |
| PhoneInfoga | DISABLED | — | Phone seeds not enabled by default |
| PeekYou | MANUAL | — | No supported programmatic automation verified |
| FaceCheck.ID | DISABLED | — | Biometric identification not in scope |
| PimEyes | DISABLED | — | Biometric identification not in scope |
| Surfface | DISABLED | — | Biometric identification not in scope |

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/searches` | Start a new investigation |
| `GET` | `/api/searches/{id}` | Search status + metadata |
| `GET` | `/api/searches/{id}/candidates` | Ranked candidate profiles |
| `GET` | `/api/searches/{id}/hypotheses` | Identity hypothesis clusters |
| `GET` | `/api/searches/{id}/evidence` | Pairwise evidence signals |
| `GET` | `/api/searches/{id}/question` | Pending Akinator question |
| `POST` | `/api/searches/{id}/question-answer` | Submit answer / hint |
| `POST` | `/api/searches/{id}/continue` | Skip question, resume |
| `POST` | `/api/searches/{id}/stop` | Cancel investigation |
| `GET` | `/api/searches/{id}/report` | Final explainable report |
| `GET` | `/api/searches/{id}/graph` | Graph-shaped nodes/edges (no Neo4j) |
| `GET` | `/api/searches/{id}/connector-runs` | Per-connector execution log |
| `POST` | `/api/searches/{id}/images` | Upload reference image (fingerprint only) |
| `GET` | `/api/connectors` | Live connector health |
| `GET` | `/api/config.js` | Runtime JS config injection |
| `GET` | `/health` | Service health |

---

## Architecture

```
PostgreSQL 17 + pgvector 0.8
├── search_runs           # investigation lifecycle
├── search_seeds          # input seeds
├── profiles              # deduplicated public accounts
├── profile_observations  # traceable raw observations per connector
├── identifiers           # usernames, emails, domains, URLs, etc.
├── profile_identifiers   # profile↔identifier relationships
├── evidence_signals      # deterministic pairwise evidence
├── identity_hypotheses   # candidate clusters
├── hypothesis_memberships
├── investigation_questions / answers
├── user_search_context   # user hints (not identity proof)
├── investigation_jobs    # persistent job queue (FOR UPDATE SKIP LOCKED)
├── text_embeddings       # all-MiniLM-L6-v2 384-D bio vectors
├── image_artifacts       # SHA-256 + pHash only; raw bytes discarded
└── reports               # final report JSONB
```

Worker uses PostgreSQL advisory locks (`pg_try_advisory_lock`) for per-search
concurrency control. No Redis. No additional queue infrastructure.

---

## Scope

Core Deus uses **publicly available information** only.

Not implemented and will not be:
- Credential theft, session hijack, OTP interception
- Private-profile bypass, authentication bypass
- Global biometric database or mass face crawling
- Scraped private breach dumps for identity correlation
- Contacting the subject

Breach-exposure tools (`pwned`, `h8mail`) are kept **out of normal correlation**
and would require explicit `scope=self_audit` invocation.

---

## Configuration

Copy `.env.example` to `.env`:

```env
DATABASE_URL=postgresql+asyncpg://osint:osint-dev@localhost:5432/osint
API_PORT=8765
GITHUB_TOKEN=           # optional — increases rate limits
AI_ADVISER_ENABLED=false
OPENAI_API_KEY=         # optional — only for advisory text
CONNECTOR_TIMEOUT_SECONDS=30
MAX_PIVOT_DEPTH=3
MAX_CONNECTOR_RUNS=30
MAX_CANDIDATES=100
MAX_QUESTIONS=3
MAX_SEARCH_DURATION_SECONDS=600
```

No `MOCK_CONNECTORS`. No `FAKE_*`. No `SIMULATE_*`.
