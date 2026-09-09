# Public-link traversal repair — 9 September 2026

## Diagnosed from actual runs

- Social Analyzer's LinkedIn CLI check returned valid `{}` with exit code 0. The adapter incorrectly called it invalid JSON. It now reports PARTIAL/inconclusive, without asserting existence or absence.
- GitHub 404 means that exact username was not found. It is not a backend crash.
- Maigret's reports contained unknown/inconclusive checks. The adapter now gives the unknown/total counts instead of suggesting every report failed to parse.
- Gemini rejected the serialized `additional_properties` schema field with HTTP 400. A supported wire schema plus strict local Pydantic validation fixes this. A real adviser request and the live investigation now recorded APPLIED. The UI exposes actual adviser status and fallback reasons.
- The planner only enriched three preferred profiles, did not follow different handles, and stopped at websites. Link traversal now follows source-observed targets with a persisted deduplication ledger, six-call batches, and bounded time/run/candidate/depth limits. `.env` increases the depth ceiling from 3 to 5 for new searches; saved searches retain their original budgets.

## Link handling

GitHub social-account fields, the profile website and Twitter field, and HTML `rel=me` links provide explicit public associations. Recognized destination accounts are retained even when destination collection is restricted. This is an association, not independently verified ownership or existence.

Ordinary HTML anchors and repository README references are weaker: they can refer to dependencies, collaborators or other people. These are collected with source URLs and opened through bounded public connectors, but do not become ownership evidence. No unrestricted recursive crawler or authentication bypass was added.

GitHub collection includes the profile README and up to three recently updated owned, non-fork repository READMEs. This is deliberately not complete repository-history coverage.

Account URL recognition includes GitHub, GitLab, Instagram, LinkedIn, Facebook, X/Twitter, Reddit, YouTube, TikTok, Twitch, Pinterest, Dev.to, Medium, Telegram, Keybase and mastodon.social. URL recognition and public HTML collection do not mean every platform provides a working rich-profile API. Login walls, JavaScript, rate limits and unsupported formats remain explicit limitations. Arbitrary Mastodon instances, Tumblr subdomains and Facebook numeric profile query URLs are not included in this recognizer yet.

Candidates are separated into publicly linked accounts, accounts with public context, and “Possible matches but nothing to analyze.” Search-relevance bonuses never change identity evidence. Zero identity evidence means insufficient support, not that the account is fake.

## Verification

- Full live/DB test run: 90 passed, 3 skipped (GHunt/HIBP self-audit inputs and GitFive login unavailable).
- Live `Aadrit` → yes → `555` acceptance completed: `388f4ee7-289a-455b-8482-8615373f89bf`. GitHub `Aadrit555` was discovered with USER_HINT_MATCH; Gemini recorded APPLIED. Social Analyzer produced SUCCESS and honest PARTIAL outcomes.
- Direct live GitHub inspection for Aadrit555: 5 real requests, SUCCESS. No LinkedIn/Instagram links in returned profile/social fields. A GitHub README reference was retained; no other account association was invented.
- Pure regression tests cover account versus post/repository URL recognition, explicit-link candidate generation without invented existence, rel=me versus ordinary anchors, and isolated candidate grouping. These tests use literal parser inputs, not simulated runtime collection.

Authenticated tools still need operator login or keys as described in IMPLEMENTATION_NOTES.md. Existing secrets were preserved. No new paid provider was added, no biometric identification was implemented, and no private-profile controls are bypassed.
