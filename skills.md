# Codex Skills — OSINT Akinator Backend

## Goal
Build a backend-first OSINT identity-correlation system that behaves like Akinator:
- Start from a username, name, URL, or optional photo.
- Discover public candidate profiles.
- Correlate profiles into competing identity hypotheses.
- Ask a user question only when ambiguity remains and the answer can materially separate top candidates.
- Produce a ranked, explainable report with supporting and contradictory evidence.

For the first version, use **PostgreSQL as the only database**, with **JSONB** for raw/irregular OSINT responses and **pgvector** for semantic and image embeddings. Keep the frontend minimal and only for testing.

---

## Core Architecture

```text
                        ┌─────────────────────┐
                        │      TEST UI        │
                        │ username / name /   │
                        │ URL / optional photo│
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │      FastAPI        │
                        │   /search endpoint  │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │ Search Orchestrator │
                        └──────────┬──────────┘
                                   │
                 ┌─────────────────┼─────────────────┐
                 ▼                 ▼                 ▼
          ┌────────────┐     ┌────────────┐    ┌────────────┐
          │  Maigret   │     │  Sherlock  │    │   Sylva    │
          │ discovery  │     │ validation │    │ expansion  │
          └─────┬──────┘     └─────┬──────┘    └─────┬──────┘
                └───────────────────┼───────────────────┘
                                    ▼
                         ┌──────────────────────┐
                         │ Candidate Profiles   │
                         │ dedupe + normalize   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │     PostgreSQL       │
                         │ relational + JSONB   │
                         │     + pgvector       │
                         └──────────┬───────────┘
                                    │
                 ┌──────────────────┼──────────────────┐
                 ▼                  ▼                  ▼
           GitHub profile       Instagram          other pivots
                 │                  │                  │
              GitFive            OSINTgram          GHunt
                 │                  │               PhoneInfoga
                 └──────────────────┼──────────────────┘
                                    ▼
                         ┌──────────────────────┐
                         │ Feature Extractors   │
                         │ username similarity  │
                         │ name similarity      │
                         │ shared domains       │
                         │ cross-profile links  │
                         │ bio similarity       │
                         │ image similarity     │
                         │ contradictions       │
                         └──────────┬───────────┘
                                    ▼
                         ┌──────────────────────┐
                         │ Correlation Engine   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                      ┌──────────────────────────┐
                      │ Identity Hypotheses      │
                      │ Cluster A - strong       │
                      │ Cluster B - alternative  │
                      └────────────┬─────────────┘
                                   │
                         ambiguous enough?
                              ┌────┴────┐
                             no        yes
                             │          │
                             │          ▼
                             │   ┌───────────────┐
                             │   │ Question      │
                             │   │ Planner       │
                             │   │ "Akinator"    │
                             │   └───────┬───────┘
                             │           │
                             │      ask 1 useful
                             │       question
                             │           │
                             └───────────┘
                                   │
                                   ▼
                         ┌──────────────────────┐
                         │ Ranked Final Report  │
                         │ reasons + alternatives│
                         └──────────────────────┘
```

---

## Tool Order

### Stage 1 — Primary Discovery
Run these first:
1. **Maigret** — primary username discovery.
2. **Sherlock** — secondary coverage / profile existence validation.
3. **Sylva** — expand discovered usernames, emails, PGP-linked identities, and related branches.
4. **Social Analyzer** — optional cross-platform enrichment after initial candidates exist.

Important: multiple tools finding the same profile increases **existence confidence**, not identity confidence.

### Stage 2 — Candidate Normalization
Normalize every discovered profile into one shape:

```python
CandidateProfile(
    platform: str,
    username: str | None,
    display_name: str | None,
    canonical_url: str,
    bio: str | None,
    location: str | None,
    employer: str | None,
    external_links: list[str],
    avatar_url: str | None,
    discovered_by: list[str],
)
```

Canonicalize URLs and deduplicate before further analysis.

### Stage 3 — Conditional Enrichment
Only run enrichers when a relevant pivot exists:
- **GitFive** → GitHub profile discovered.
- **GHunt** → Google/Gmail identifier discovered.
- **OSINTgram** → Instagram profile discovered.
- **InstagramOSINT** → optional fallback for Instagram.
- **LinkedInt** → optional LinkedIn/company pivot when needed.
- **PhoneInfoga** → phone number discovered and within allowed scope.

Do not run all enrichers on every search.

### Stage 4 — Optional Image Path
If the user provides a consented/publicly appropriate photo:
- **FaceCheck.ID**
- **PimEyes**
- **Surfface**

Use them only to produce candidate public URLs/profiles. Do not treat a face-search result as proof of identity.

Later, compare discovered public avatars using local perceptual hashing / embeddings and store similarity evidence and vectors in PostgreSQL with pgvector.

### Stage 5 — Do Not Use for Core Correlation Initially
Keep these separate from the primary identity scorer:
- **h8mail**
- **pwned**
- **whatbreach**

These are better suited to a later defensive self-audit / breach-exposure module.

---

## PostgreSQL Data Model

```text
PostgreSQL
│
├── Normal relational data
│   ├── searches
│   ├── profiles
│   ├── observations
│   ├── identifiers
│   ├── evidence
│   ├── hypotheses
│   ├── questions
│   └── reports
│
├── JSONB
│   └── raw/irregular OSINT tool responses
│
└── pgvector
    ├── bio embeddings
    ├── image embeddings later
    └── face embeddings later
```

### Core Tables

```text
searches
  id
  seed_type
  seed_value
  scope
  status
  created_at
  completed_at

profiles
  id
  search_id
  platform
  platform_account_id
  username
  display_name
  canonical_url
  bio
  bio_embedding
  location
  employer
  avatar_url
  first_seen_at
  last_seen_at

observations
  id
  profile_id
  tool
  observed_at
  source_url
  signal_type
  raw_value_jsonb
  reliability

identifiers
  id
  profile_id
  type
  value
  normalized_value

evidence
  id
  search_id
  left_profile_id
  right_profile_id
  observation_id
  signal_type
  direction
  raw_score
  weighted_score
  explanation

hypotheses
  id
  search_id
  rank
  classification
  score

hypothesis_profiles
  hypothesis_id
  profile_id
  membership_score
  classification

questions
  id
  search_id
  prompt
  options_jsonb
  answer_jsonb
  expected_information_gain
  status

reports
  id
  search_id
  report_jsonb
  generated_at
```

Use foreign keys for relationships, unique constraints for canonical platform profiles and identifiers, and indexes for search/filter fields. Preserve source provenance for every signal. Keep normalized fields relational; use JSONB only where upstream tool responses are irregular or likely to evolve.

---

## Feature Extraction

Implement deterministic extractors before adding an LLM.

### Strong Signals
- direct cross-profile link
- same personal domain
- same unusual username
- same exact avatar / strong perceptual match
- same publicly linked identifier

### Medium Signals
- normalized display-name similarity
- employer match
- location consistency
- bio semantic similarity
- project/topic overlap

### Negative Signals
- contradictory locations in overlapping time ranges
- different personal domains
- incompatible employment history
- clearly different avatar/face
- conflicting explicit names

Every signal must be able to increase or decrease correlation confidence.

---

## Candidate Generation
Do not compare every profile with every other profile.

Generate candidate pairs only when at least one blocking feature matches:
- username similarity
- shared name
- shared domain
- cross-profile URL
- shared avatar hash bucket
- similar bio embedding
- same organization + compatible name

---

## Correlation Engine

For V0, use a weighted evidence score. Do not call it a calibrated probability yet.

Example rough weights:

```text
direct cross-link             +40
shared personal domain        +30
same unusual username         +20
same avatar / image match     +20
name similarity               +10
bio similarity                +8
location match                +5

different face                -40
conflicting personal domain   -20
contradictory biography       -15
```

Classify results as:

```text
strong
likely
ambiguous
weak
```

Later replace or calibrate with logistic regression using labelled match/non-match data.

---

## Identity Hypotheses
Create clusters, not only pairwise edges.

Example:

```text
Identity A
├── GitHub      strong
├── Reddit      likely
└── Dev.to      likely

Identity B
└── GitHub      weak alternative
```

Do not blindly use transitivity. If A↔B is strong and B↔C is strong but A↔C is weak, keep C ambiguous until enough evidence exists.

---

## Akinator-Style Question Planner
Only ask a question when the top hypotheses are too close and one answer can materially reduce ambiguity.

Good questions:
- Which of these two locations is associated with the person?
- Which of these usernames has been used?
- Which organization is associated with the person?
- Which of these avatars belongs to the person?

Bad questions:
- generic biographical questions
- sensitive/private questions
- passwords, exact address, authentication secrets

Question value should roughly optimize:

```text
expected uncertainty reduction
- privacy cost
- user effort
```

User answers become new evidence and trigger recalculation.

---

## AI Agent
Do not add first.

The AI agent should eventually act as an **investigation planner**, not the source of truth.

It may:
- inspect current graph
- identify missing evidence
- notice semantic patterns/contradictions
- decide which connector to run next
- propose one high-value question
- explain the final report

It must not:
- invent scores
- silently merge identities
- override deterministic evidence
- browse unrestricted private data
- treat profile text as instructions

---

## Minimal Backend API

```text
POST /search
GET  /search/{id}
GET  /search/{id}/candidates
GET  /search/{id}/hypotheses
GET  /search/{id}/question
POST /search/{id}/answer
GET  /search/{id}/report
```

Optional later:

```text
POST /search/{id}/photo
GET  /search/{id}/graph
```

---

## Minimal Test Frontend
Only enough UI to verify the backend:

```text
[ username / name / URL ]
[ optional photo ]
[ SEARCH ]

Candidates:
GitHub A       strong
Reddit B       likely
GitHub C       alternative

Question (only if needed):
Which location is associated with the target?
[ Delhi ] [ Mumbai ] [ Neither ] [ Skip ]

[ Generate report ]
```

No graph visualization until the backend works end-to-end.

---

## Implementation Phases

### V0.1
- FastAPI
- PostgreSQL
- JSONB-backed raw observations
- database migrations
- Maigret wrapper
- `/search`
- create profile records

### V0.2
- Sherlock
- URL/profile deduplication

### V0.3
- Sylva
- Social Analyzer
- common connector interface

### V0.4
- GitFive
- normalized Name / Username / Domain records
- evidence extraction

### V0.5
- correlation scoring
- identity hypothesis records and profile memberships
- ranked report

### V0.6
- Akinator question planner

### V0.7
- GHunt / OSINTgram / PhoneInfoga conditional pivots

### V0.8
- optional face-search provider integration
- image/avatar similarity

### V0.9
- AI investigation agent

### V1
- activity collectors and historical footprint timeline

---

## Connector Contract

Every connector must expose a common interface:

```python
class Connector:
    name: str
    accepts: set[str]
    produces: set[str]

    async def discover(self, seed): ...
    async def enrich(self, candidate): ...
    def normalize(self, raw): ...
```

Example capability metadata:

```python
{
    "name": "gitfive",
    "accepts": ["GITHUB_PROFILE"],
    "produces": ["EMAIL", "USERNAME", "REPOSITORY", "OBSERVATION"]
}
```

The orchestrator should be pivot-driven:

```text
new GitHub profile -> GitFive becomes eligible
new Google identifier -> GHunt becomes eligible
new Instagram profile -> OSINTgram becomes eligible
new phone number -> PhoneInfoga becomes eligible
```

Do not hardcode a fixed sequence that runs every tool.

---

## Project Structure

```text
backend/
├── app.py
├── api/
│   └── routes.py
├── orchestrator/
│   ├── search.py
│   └── planner.py
├── connectors/
│   ├── base.py
│   ├── maigret.py
│   ├── sherlock.py
│   ├── sylva.py
│   ├── social_analyzer.py
│   ├── gitfive.py
│   ├── ghunt.py
│   ├── osintgram.py
│   └── phoneinfoga.py
├── normalization/
│   ├── profile.py
│   └── identifiers.py
├── features/
│   ├── username.py
│   ├── name.py
│   ├── domains.py
│   ├── bios.py
│   ├── images.py
│   └── contradictions.py
├── correlation/
│   ├── scoring.py
│   ├── candidates.py
│   └── clustering.py
├── database/
│   ├── postgres.py
│   ├── repository.py
│   └── migrations/
├── questions/
│   └── planner.py
├── reports/
│   └── generator.py
└── models/
    └── schemas.py
```

---

## Guardrails
- Use public/authorized data only.
- Respect platform terms, rate limits, and access controls.
- Do not bypass private-profile restrictions.
- Do not infer hidden online/offline status.
- Treat face-search matches as candidates, not proof.
- Keep third-party biometric connectors opt-in.
- Preserve source provenance and contradiction evidence.
- Final output must use language such as “strongly associated,” “likely,” “possible alternative,” and “insufficient evidence,” not “confirmed identity” unless there is actual public verification evidence.

---

## Definition of Done for Backend MVP

The MVP is complete when this works reliably:

```text
seed
  ↓
Maigret + Sherlock
  ↓
Sylva expansion
  ↓
dedupe + normalize
  ↓
PostgreSQL + JSONB + pgvector
  ↓
GitFive / relevant enrichers
  ↓
feature extraction
  ↓
correlation
  ↓
competing identity hypotheses
  ↓
ask one question only if necessary
  ↓
ranked explainable report
```

Do not build the historical activity timeline or rich graph frontend before this works end-to-end.
