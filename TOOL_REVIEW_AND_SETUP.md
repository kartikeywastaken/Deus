# Tool review and public-profile integration

Reviewed on 9 September 2026. These are separate decisions, not a claim that every named framework is integrated.

| Project | Decision | Reason |
| --- | --- | --- |
| [Seekr](https://github.com/seekr-osint/seekr) | Reviewed, not installed | A separate Go/web application with its own storage and orchestration. Its broad framework does not directly solve our public-profile adapter gaps. |
| [H.I.V.E](https://github.com/Shad0w-ops/H.I.V.E) | Reviewed, not installed | Combines Sherlock with infrastructure, phone and leaked-data functions. We already call Sherlock directly; the other modules are outside this public-account-link task. |
| [GhostRecon](https://github.com/KawaCoder/GhostRecon/blob/master/Grecon) | Reviewed, not installed | An interactive Linux shell framework with system-level paths and commands, not a bounded backend connector contract. |
| [email2phonenumber](https://github.com/martinvigo/email2phonenumber) | Not integrated | Uses account-recovery probing to uncover non-public phone numbers. That functionality is excluded. Upstream also warns that supported services added protections. The catalogue explicitly reports DISABLED. |
| [InstagramOSINT](https://github.com/sc1341/InstagramOSINT) | Reviewed, not installed | Archived upstream. No verified maintained collection interface to add alongside the selected Instagram adapter. |
| [Osintgram](https://github.com/Datalux/Osintgram) | Restricted real integration implemented | Calls pinned upstream `Osintgram.get_user` through an isolated read-only client. Not the full interactive application. Live authentication remains unverified until an operator supplies a session. |

## Osintgram boundaries

The reviewed checkout is commit `c8ba1f0ae119c7def2e2ff8cf694a85b2ca49be0`. Source-file hashes are enforced before import. Upstream's global TLS-verification override is restored immediately, before any network request.

The wrapper bypasses the constructor, login, follow checks, file-output commands and interactive shell. Only one `username_info` request is allowed per invocation, with a ten-second network timeout and twenty-second process deadline. No follower/following enumeration, contact harvesting, recovery endpoints, geolocation, or follow requests are available through the wrapper.

The output includes only public-profile ID, handle, name, bio, and explicit external/bio links. Private or unknown visibility returns no profile fields. Nested provider fields, email/phone fields and follower data are excluded from normalized results. Challenges and expired sessions stop collection; they are not bypassed or retried with a fresh login.

### Local installation completed

- Checkout: `.local/tools/osintgram-source`
- Isolated interpreter: `.local/tools/osintgram-venv/bin/python`
- Dependencies: `requirements-osintgram.txt`
- Real source import check: READY, with TLS verification restored.
- `.env` points to these installations. `OSINTGRAM_SESSION_FILE` is deliberately empty.

To activate collection, supply an authorized existing Osintgram/instagram-private-api settings export explicitly through `OSINTGRAM_SESSION_FILE`. It must contain a valid session cookie, be smaller than 100 KB, and have private file permissions (0600). Keep it under an ignored private directory. Do not paste the session into chat. The backend never discovers browser cookies or logs into an account on its own. Restart the worker after changing configuration.

Without that file the connector returns AUTH_REQUIRED. This is an implemented adapter awaiting authentication, not a simulated success. Its compatibility with Instagram's current authenticated endpoint cannot be established by import tests alone.

### Reproduce the installation elsewhere

Clone the upstream repository into a dedicated tool directory, check out the exact reviewed commit, create a separate Python virtual environment and install `requirements-osintgram.txt` there. Configure the three explicit paths in `.env`. Do not run upstream's full install shell script or install its interactive dependencies into the application environment.

Check the bridge without contacting Instagram:

```sh
.local/tools/osintgram-venv/bin/python backend/connectors/osintgram_public.py --check .local/tools/osintgram-source
```

### Future patch workflow

Review upstream changes to the lookup method, imports, authentication, TLS handling and request behavior before changing the pinned commit or hash allowlist. Test public-only filtering, private-profile rejection, changed usernames, session expiry, rate limits and subprocess cancellation. Then run a real lookup against an operator-controlled public account with an authorized session. Do not add arbitrary upstream command passthrough. No recovery-probing patch workflow is provided for email2phonenumber.

## Maigret / Sherlock / Social Analyzer

The reviewed discovery list expands from 20 requested platforms to 30. Exact names are resolved from installed databases, including DEV Community and mastodon.social aliases. Unsupported definitions are reported rather than silently assumed to work. Maigret uses a filtered database so third-party Instagram/Steam mirrors are not selected implicitly.

New searches allow 60 candidates and 45 connector invocations, up from 30 each. The five-level traversal and ten-minute overall deadline remain bounded. Existing searches keep their saved budgets.

Maigret now uses eight concurrent connections, OS DNS resolution, no automatic retries, no recursive extraction, and no automatic database updates. Discovery has a sixty-second outer budget; its child process is bounded to fifty-five seconds with output limits and process-group cleanup. Broad discovery and explicitly linked account traversal remain different stages.

Parsed reports survive individual inconclusive checks. Per-site diagnostics distinguish FOUND, NOT_FOUND, BLOCKED, RATE_LIMITED, ACCESS_RESTRICTED, TIMEOUT and INCONCLUSIVE. PARTIAL means useful/reportable work exists despite incomplete checks, not that the whole tool crashed. Missing/invalid reports still fail honestly. No CAPTCHA bypass, proxy rotation or rate-limit evasion was added.

Social Analyzer's reviewed host mapping expands too, but it only runs when the installed database contains the requested platform. Public-link recognition additionally supports Bluesky, Threads, SoundCloud, Spotify, Behance, Dribbble, CodePen, Replit, last.fm and Linktree. Recognition does not guarantee a platform permits complete public collection.

## Verification

The final real-network/PostgreSQL suite passed 98 tests, with five skips: four credential/operator-input-dependent checks and one unauthenticated GitHub check that was rate-limited. JavaScript syntax, Python lint, and the pinned Osintgram import/TLS check passed. The no-session Osintgram path was exercised and correctly returned AUTH_REQUIRED with zero profiles. The optional Osintgram live test also requires `DEUS_TEST_INSTAGRAM_USERNAME` for an operator-controlled public profile.

Expanded live acceptance run `9b4b651c-b73b-4052-a85d-86fc62f5c9ea` completed in 159.5 seconds and found a real public link from `https://dev.to/aadrit555` to `https://github.com/aadrit555`. Maigret returned useful PARTIAL reports, not whole-run failures. Gemini returned 503/timeouts during this run; the deterministic fallback completed the workflow. This run retained its earlier 30-candidate/30-call limits; subsequent searches use the new limits.

Pure parser tests are distinct from production collection. Runtime collection has no fixtures or generated account results. Authenticated Osintgram cannot be claimed live-verified without the missing session; the upstream import/TLS check is a dependency check only.
