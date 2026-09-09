Here's what's left purely in terms of **code to write**, ordered by impact:

---

## Priority 1 — Broken / produces wrong output right now

### 1. `score: 0.0` on almost all candidates
**Root cause:** The scorer only compares profiles *against each other* (pairwise). If only one profile is found (common case for exact username searches), there's no pair to compare → zero score → report is useless.

**Fix:** Seed-match bonus in [`backend/correlation/engine.py`](file:///Users/kartik/Documents/ChatGPT/Deus/backend/correlation/engine.py) — if a profile's username exactly equals the search seed, assign it a base `+15` score directly. ~20 lines.

---

### 2. Social Analyzer only covers 2 platforms
**Root cause:** [`backend/connectors/social_live.py`](file:///Users/kartik/Documents/ChatGPT/Deus/backend/connectors/social_live.py) line 25 has a hardcoded dict with only `github.com` and `reddit.com`. When Maigret finds a Twitter or Instagram profile, Social Analyzer returns `UNAVAILABLE` — wasted enrichment slot.

**Fix:** Expand the hostname→site dict to cover all 20 platforms Maigret checks. ~15 lines.

---

## Priority 2 — Missing features with code stubs already in place

### 3. Name-seed doesn't chain into discovery
**Root cause:** `seed_type=name` → `github_search` runs → finds a profile with a username → **stops there**. The username extracted from that result never gets fed back into Maigret/Sherlock.

**Fix:** In [`backend/investigation/orchestrator.py`](file:///Users/kartik/Documents/ChatGPT/Deus/backend/investigation/orchestrator.py), after `github_search` returns, extract discovered usernames and add them as Maigret/Sherlock pivot inputs. ~30 lines.

---

### 4. Disambiguation question never fires from real data
**Root cause:** `plan_disambiguation_question()` in [`backend/investigation/question_planner.py`](file:///Users/kartik/Documents/ChatGPT/Deus/backend/investigation/question_planner.py) only asks about `location` or `organization` — fields that are almost always empty on discovered public profiles. So this question path is effectively dead.

**Fix:** Add question types for: platform choice ("this Twitter and this GitHub — same person?"), display name disambiguation, repository overlap. ~60 lines.

---

### 5. GHunt connector (email → Google account)
**Root cause:** `backend/connectors/ghunt.py` exists, returns `AUTH_REQUIRED`. The subprocess invocation is not written.

**Fix:** Write `ghunt email <address>` subprocess call + parse its JSON output into `CandidateProfile` + `ObservationArtifact`. ~80 lines. **Requires operator to run `ghunt login` once.**

---

### 6. GitFive connector (GitHub → commit emails)
**Root cause:** `backend/connectors/gitfive.py` exists, returns `MANUAL`. The subprocess invocation is not written.

**Fix:** Write `gitfive hunt <github_url>` subprocess call + parse output. High value — surfaces real email addresses from public commit history. ~80 lines. **Requires a scoped GitHub token.**

---

## Priority 3 — New subsystems

### 7. SSE live events
**Current:** Frontend polls `GET /api/searches/{id}` every 1 second.  
**Fix:** Add `GET /api/searches/{id}/events` returning `text/event-stream`. Worker writes events to a `search_events` table (`CONNECTOR_STARTED`, `CANDIDATE_DISCOVERED`, `QUESTION_CREATED`, `COMPLETED`). SSE endpoint tails that table. Frontend switches from `setInterval` to `EventSource`. ~250 lines total.

---

### 8. Face comparison
**Current:** Image upload works (stores SHA-256 + pHash). Face embedding/comparison is not wired.  
**Fix:** 
- Add `face_embeddings` table to migrations (pgvector column, 512-D for `insightface`)
- `backend/embeddings/faces.py` — runs `insightface` locally, embeds avatar URLs
- `backend/extraction/images.py` — already has `extract_image_evidence()` stub, wire it to face cosine distance
- New `FACE_SIMILARITY` signal type in scorer

~300 lines + `insightface` in `pyproject.toml`.

---

### 9. Breach self-audit (`scope=self_audit`)
**Current:** `scope` field exists on `SearchRun` model, accepted in API. Nothing different happens.  
**Fix:** In orchestrator, when `scope=self_audit`, after email identifiers are discovered, call HIBP API (`haveibeenpwned.com/api/v3/breachedaccount/{email}`) and store results as `ObservationArtifact` with `signal_type=BREACH_EXPOSURE`. Kept completely separate from identity correlation evidence. ~100 lines.

---

### 10. Frontend redesign
**Current:** 250-line `app.js` + 99-line `styles.css`. Functional, looks like a dev console.  
**What's needed:**
- Evidence panel (show which signals fired, with weights)
- Hypothesis cluster view (grouped profiles with score bar)
- Graph visualization (D3.js or Cytoscape on `/api/searches/{id}/graph` data)
- Report page with formatted output instead of raw JSON
- Live status with connector progress indicators

~1,000–1,500 lines of HTML/CSS/JS.

---

## Summary by effort

| # | Item | Effort | Files |
|---|------|--------|-------|
| 1 | Score fix for single-candidate | **30 min** | `correlation/engine.py` |
| 2 | SA platform expansion | **45 min** | `connectors/social_live.py` |
| 3 | Name-seed → username pivot chain | **2 hrs** | `investigation/orchestrator.py` |
| 4 | Disambiguation questions from real data | **2 hrs** | `investigation/question_planner.py` |
| 5 | GHunt subprocess + parser | **3 hrs** | `connectors/ghunt.py` |
| 6 | GitFive subprocess + parser | **3 hrs** | `connectors/gitfive.py` |
| 7 | SSE live events | **4 hrs** | new `api/events.py` + `app.js` |
| 8 | Face embedding + comparison | **1 day** | new `embeddings/faces.py`, migrations |
| 9 | Breach self-audit scope | **3 hrs** | `investigation/orchestrator.py` |
| 10 | Frontend redesign | **2 days** | `frontend/` |

Items 1 and 2 are the ones you should do **right now** — they fix actual wrong output. Want me to implement them?



why isnt this still working oh and also the ai assist is working fine right? and what else can do to narrow down our findings even more? why isnt social analyze working recursively to find and open the link in the repos it finds? additionally what im aiming towards is that lets say after aadrit555 id if it has linkedin attached or some social like instagram i want u to connect them since they were linked to his account and then list all his accounts which were found dont limit this just to github that has to support all major socials. and for lets say accounts which do not have other links kind of isolate them or show them separately like "Possible matches but nothing to analyze".