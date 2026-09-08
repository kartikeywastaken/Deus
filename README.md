# Deus

Backend-first public-profile discovery and explainable identity correlation.
The application defaults to **live collection**. Failed or unavailable connectors
never fall back to fictional profiles. Matching usernames are candidates, not proof
of shared identity; scores are not probabilities.

## Working now

- GitHub REST: public account ID, name, bio, location, organization, website, avatar
  URL, and publicly listed social links with source provenance.
- Maigret 0.6.5 and Sherlock 0.16.0: actual subprocess execution and CSV parsing.
  Initial selection is GitHub, Reddit, and Dev.to. Maigret may also check bundled
  mirrors such as GitHubGist. This is bounded, not whole-web coverage.
- Social Analyzer 0.45: actual JSON checks for discovered GitHub/Reddit profiles.
  Page titles and existence observations are retained; detection percentages do
  not become identity probabilities.
- PostgreSQL relational records, raw JSONB payloads, pgvector schema/repositories,
  evidence extraction, conservative clustering, optional questions, ranked reports,
  and graph-shaped API output.
- Minimal UI with public-source links, evidence, limitations, and per-tool errors.

## Architecture

```text
username / GitHub profile URL
  → bounded live discovery
  → normalize + deduplicate
  → PostgreSQL observations and JSONB provenance
  → conditional public enrichment
  → positive and negative pair evidence
  → conservative competing clusters
  → useful question only when needed
  → explainable report + graph API
```

Searches execute synchronously within their HTTP request and commit as a workflow
step. Stop does not interrupt an executing initial request. Durable background
jobs, streaming progress, and production multi-user authentication are not
implemented; bind this development app to loopback only.

## Run with Docker PostgreSQL

Requires Python 3.12+ and PostgreSQL with pgvector (Docker is one option).

```bash
cp .env.example .env
docker compose up -d
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,live]"
python -m alembic upgrade head
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765/> or <http://127.0.0.1:8765/docs>.
Do not overwrite an existing `.env` containing your settings.

## This workspace's local setup

A separate development PostgreSQL 17 cluster was initialized in `.local/postgres`,
with database `deus` on `127.0.0.1:55432`. pgvector 0.8.6 is installed through
Homebrew. `.env` points at this database; `.env`, `.local/`, and `.venv/` are ignored
by Git. This uses local trust authentication and is not suitable for a shared server.
The app uses port 8765 because other services occupied ports 8000 and 8001.

Restart the database only if it is stopped:

```bash
/opt/homebrew/opt/postgresql@17/bin/pg_ctl \
  -D /Users/kartik/Documents/ChatGPT/Deus/.local/postgres \
  -l /Users/kartik/Documents/ChatGPT/Deus/.local/postgres.log \
  -o '-h 127.0.0.1 -p 55432 -k /Users/kartik/Documents/ChatGPT/Deus/.local' start
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765
```

Use `pg_ctl -D /Users/kartik/Documents/ChatGPT/Deus/.local/postgres stop` to stop
this project's database without deleting its data.

## API

```text
GET  /api/connectors
POST /api/searches
GET  /api/searches/{id}
GET  /api/searches/{id}/candidates
GET  /api/searches/{id}/hypotheses
GET  /api/searches/{id}/evidence
GET  /api/searches/{id}/question
POST /api/searches/{id}/question-answer
POST /api/searches/{id}/continue
POST /api/searches/{id}/stop
GET  /api/searches/{id}/report
GET  /api/searches/{id}/graph
GET  /health
```

`GET /health` is process liveness, not a database readiness check.

```bash
curl http://127.0.0.1:8765/api/searches \
  -H 'content-type: application/json' \
  -d '{"seed_type":"username","value":"YOUR_PUBLIC_USERNAME","scope":"self_audit"}'
```

Live mode rejects name, email, phone, image, and non-GitHub URL seeds until reviewed
connectors exist. `MAX_QUESTIONS=0` produces reports without a question stage.

## Rate limits and failures

Set an optional `GITHUB_TOKEN` in your local `.env` for authenticated public API
requests. Never paste a token into chat or commit it. Without it, unauthenticated
rate limits can interrupt collection. The adapter records rate limits and does not
bypass them. It preserves a fetched profile if social-link collection fails.

Availability is exposed at `/api/connectors`; actual outcomes appear in reports.
`PARTIAL`, `FAILED`, `RATE_LIMITED`, and `UNAVAILABLE` mean collection was incomplete,
not that the person has no accounts. CLI request counts are estimates from report
rows, not exact network counters. Tool detections can be false positives.

## Tests

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest
TEST_DATABASE_URL=postgresql+asyncpg://deus@127.0.0.1:55432/deus \
  .venv/bin/python -m pytest
```

Offline tests use isolated doubles. Legacy fixture scenarios require explicit
`MOCK_CONNECTORS=true`; the application never enables this automatically.
PostgreSQL tests create unique temporary schemas and remove only those schemas.
The actual application database is not seeded with fictional profiles.

## Not implemented / blocked

- Sylva: intended upstream repository/interface is not verified.
- GitFive: not integrated; upstream requires interactive login and has usage
  restrictions. GitHub REST is an independent connector, not a GitFive simulation.
- LinkedIn, Instagram, Facebook, GHunt, and phone lookups: no live adapters yet.
- Embedding model inference, AI investigator, rich graph UI, historical activity:
  not implemented. Vector storage alone does not run a model.
- Face-search / biometric identification across the web: not implemented.

Public or authorized data only; no private-profile bypass, credential harvesting,
breach lookups, or identity claims based solely on images.

## Verified upstream interfaces

- [GitHub users](https://docs.github.com/en/rest/users/users#get-a-user)
- [GitHub public social links](https://docs.github.com/en/rest/users/social-accounts#list-social-accounts-for-a-user)
- [Maigret CLI](https://maigret.readthedocs.io/en/latest/command-line-options.html)
- [Sherlock](https://github.com/sherlock-project/sherlock)
- [Social Analyzer](https://github.com/qeeqbox/social-analyzer)
- [GitFive requirements](https://github.com/mxrch/GitFive)
