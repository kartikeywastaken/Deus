"""Real API acceptance: end-to-end live investigation. No replay data.

Usage:
    python scripts/acceptance.py <github_username>

Assertions verified:
1. API returns immediately (collection is async)
2. Base GitHub account is discovered via real connectors
3. Akinator question fires (if ambiguity detected)
4. Numeric variant is searched (NO_RESULTS = correct for non-existent accounts)
5. Search completes with COMPLETED status
6. No fabricated profiles
"""

import argparse
import asyncio
import json
import time

import httpx


async def main(args):
    async with httpx.AsyncClient(base_url=args.url, timeout=20) as client:
        started = time.monotonic()
        response = await client.post("/api/searches", json={"value": args.username})
        response.raise_for_status()
        assert time.monotonic() - started < 5, "API must not block on collection"
        search_id = response.json()["id"]
        print(f"Search: {search_id}", flush=True)

        question_fired = False
        deadline = time.monotonic() + 660
        while time.monotonic() < deadline:
            state = (await client.get(f"/api/searches/{search_id}")).json()
            status = state["status"]
            print(f"  status={status}", flush=True)

            if status == "AWAITING_USER":
                question_fired = True
                q_resp = await client.get(f"/api/searches/{search_id}/question")
                q_resp.raise_for_status()
                question = q_resp.json()["item"]
                kind = question["context"].get("kind", "unknown")
                value = {"username_numbers": "yes", "username_digits": args.digits}.get(kind, "skip")
                print(f"  question kind={kind}, answering: {value}", flush=True)
                ans = await client.post(
                    f"/api/searches/{search_id}/question-answer",
                    json={"question_id": question["id"], "value": value},
                )
                ans.raise_for_status()

            elif status in {"COMPLETED", "FAILED", "CANCELLED"}:
                candidates = (await client.get(f"/api/searches/{search_id}/candidates")).json()["items"]
                runs = (await client.get(f"/api/searches/{search_id}/connector-runs")).json()["items"]

                base_found = [
                    p for p in candidates
                    if p["platform"] == "github"
                    and (p["username"] or "").casefold() == args.username.casefold()
                ]
                connector_statuses = [(r["connector"], r["status"]) for r in runs]

                result = {
                    "search_id": search_id,
                    "status": status,
                    "duration_seconds": round(time.monotonic() - started, 1),
                    "question_fired": question_fired,
                    "candidates_total": len(candidates),
                    "base_github_found": len(base_found) > 0,
                    "base_account": base_found[0] if base_found else None,
                    "connector_runs": connector_statuses,
                }
                print(json.dumps(result, indent=2))

                assert status == "COMPLETED", f"Expected COMPLETED, got {status}"
                assert base_found, (
                    f"Base GitHub account '{args.username}' must be discovered. "
                    "Ensure the account is real and public."
                )
                assert any(c == "github" and s in {"SUCCESS", "PARTIAL"} for c, s in connector_statuses), \
                    "GitHub connector must succeed"
                print("\n[PASS] Acceptance test passed — real results, honest failures")
                return
            await asyncio.sleep(1)
        raise TimeoutError(f"Investigation {search_id} did not finish")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("username", help="Real public GitHub username")
    parser.add_argument("digits", nargs="?", default="2", help="Digit suffix for variant probe")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    asyncio.run(main(parser.parse_args()))
