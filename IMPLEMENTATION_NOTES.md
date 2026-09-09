# September 9 implementation and verification

This update builds on Claude's commits `7a2d57a` and `3c62d87`. Gemini remains the
adviser; existing GitHub/Gemini credentials are preserved. No runtime fixtures,
synthetic accounts, fake embedding vectors, or simulated connector fallbacks were added.

## Checklist status

| Item | Implementation |
| --- | --- |
| Singleton scores | Exact username adds 15/100 **search relevance**, including singletons. `identity_score` and identity classification stay unchanged. An exact username clue gets a separate non-additive 15-point relevance bonus. |
| Social Analyzer | Host coverage is checked against its installed site database. Unsupported sites do not consume enrichment slots. A detection must match the canonical account URL, not merely the host. The installed 0.45 database has 17 of the requested platform hosts; unsupported Twitter/Tumblr/Stack Overflow checks are not fabricated. |
| Name discovery | Up to three observed GitHub usernames from a name search feed bounded GitHub/Maigret/Sherlock pivots. Ledger fingerprints prevent repeating completed inputs. |
| Questions | Observed display names, projects, broad locations, organizations, or platforms can distinguish branches. Answers choose enrichment priorities, not identity merges or evidence bonuses. Neither/skip remain available. |
| GHunt | New opt-in subprocess adapter uses GHunt 2.3.4's `just_gaia_id` metadata lookup for explicitly supplied self-audit email seeds. It does **not** run the broad email CLI: that also collects maps/calendar information, and the inspected 2.3.4 JSON path contains unresolved variables. No private-name lookup, face analysis, or contact-list import. Requires operator login. |
| GitFive | New opt-in adapter invokes the verified `light` command, not nonexistent `hunt`. Only its anchored email-results section is parsed. The full `user` workflow is deliberately excluded: upstream generates guessed emails and creates/deletes remote repositories. Commit email authorship is explicitly unverified. Requires operator login and upstream usage review. |
| SSE | `search_events` stores transactional events; `/api/searches/{id}/events` streams IDs, reconnects using Last-Event-ID, and emits terminal completion. Frontend uses EventSource with polling fallback. |
| Face comparison | Not implemented. Facial identification remains disabled. Existing non-biometric SHA-256/pHash upload support is preserved. |
| HIBP | New opt-in API v3 connector for an explicitly supplied own-email seed with `email_self_audit_confirmed=true`. Not triggered by discovered emails. Only breach names are retained, separately from identity evidence. Requires a genuine subscription key. |
| Frontend | Responsive dashboard, candidate relevance, hypothesis clusters, evidence contributions, selectable SVG graph, live connector progress, formatted/printable report, reconnect and saved-search resume. No CDN or demo graph data. |

## Configuration and operator actions

New settings are in `.env` and `.env.example`. Existing secrets were not changed.
The real GHunt/GitFive packages are installed in isolated `.local/tools/` environments
because their httpx/Pillow requirements conflict with the main application's versions.
Their Python paths are already configured locally. No login was performed on your behalf.

From the repository root, authenticate interactively if you choose to enable them:

```sh
.local/tools/ghunt/bin/python -c 'from ghunt.ghunt import main; main()' login
.local/tools/gitfive/bin/python -c 'from gitfive.gitfive import main; main()' login
```

Then set `GHUNT_ENABLED=true` / `GHUNT_AUTH_READY=true` and/or
`GITFIVE_ENABLED=true` / `GITFIVE_AUTH_READY=true`. GitFive's own login is required;
an existing `GITHUB_TOKEN` is not a substitute. Review upstream usage restrictions.

For your own breach audit, put a real key in `HIBP_API_KEY` and set
`HIBP_ENABLED=true`. Never put credentials into chat or commit `.env`.
The email UI explicitly asks permission to send that email to the enabled providers.
No third-party account credentials are requested by the app.

Restart the API and worker after changing configuration:

```sh
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m backend.worker
# Separate terminal:
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765
```

Use one worker for the local setup. Multiple workers are supported by row leases
and per-search advisory locks, but are not needed for this console. Only stop
processes belonging to this repository. Do not overwrite an existing `.env`.
This is a loopback development app, not a public multi-user deployment.

## Checks

```sh
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://deus@127.0.0.1:55432/deus \
DEUS_TEST_USERNAME=Aadrit555 DEUS_TEST_API_URL=http://127.0.0.1:8765 \
  .venv/bin/python -m pytest -q
.venv/bin/python scripts/acceptance.py Aadrit 555
.venv/bin/python -m alembic check
```

Live authenticated tests skip unless `DEUS_TEST_EMAIL` / the appropriate login
and enablement are supplied. They never replay sample service responses.
Offline tests exercise pure calculations, parser inputs, URL validation and real
bounded local subprocess behavior; those inputs never become runtime profiles.

Verified live during development:

- Name `Aadrit` produced a GitHub search followed by nine real username connector
  runs, a question, enrichment, and a completed report (search
  `045253ef-acee-46ce-beec-f6648e675c62`).
- `Aadrit` → yes → `555` returned `github @Aadrit555` with USER_HINT_MATCH and
  reached a report (search `0d33bac1-900a-4a70-a03d-bec9923bfb38`).
- Persisted SSE events and Last-Event-ID replay were inspected against the running API.
- Both isolated authenticated tool installations expose their verified CLI help.
- GHunt authenticated collection, GitFive authenticated collection, and paid HIBP
  queries are **not live-verified**: operator authentication/key are still missing.

Real sites can return rate limits, CAPTCHAs, errors or false positives. Those are
collection limitations, not proof of identity or absence. Initial discovery reserves
some candidate capacity for later clues; hitting a cap is explicitly PARTIAL.

## Inspected primary sources

- [GitFive commands and usage](https://github.com/mxrch/GitFive)
- [GHunt commands](https://github.com/mxrch/GHunt)
- [HIBP API](https://haveibeenpwned.com/API/v3)
- [Social Analyzer](https://github.com/qeeqbox/social-analyzer)
- [Gemini async client lifecycle](https://googleapis.github.io/python-genai/)

The installed wheel sources were also inspected; the CLI examples in the supplied
checklist were not treated as executable specifications.
