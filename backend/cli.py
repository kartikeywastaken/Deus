"""Interactive client for the same durable API workflow used by the console."""

import argparse
import asyncio
import json
import time

import httpx


async def search(args):
    async with httpx.AsyncClient(base_url=args.url, timeout=20) as client:
        response = await client.post("/api/searches", json={"value": args.username})
        response.raise_for_status()
        search_id = response.json()["id"]
        print(f"Search: {search_id}", flush=True)
        deadline, previous = time.monotonic() + 900, None
        while time.monotonic() < deadline:
            response = await client.get(f"/api/searches/{search_id}")
            response.raise_for_status()
            state = response.json()
            if state["status"] != previous:
                print(state["status"], flush=True)
                previous = state["status"]
            if state["status"] == "AWAITING_USER":
                q = (await client.get(f"/api/searches/{search_id}/question")).json()["item"]
                print(q["question_text"])
                print(" / ".join(f"{o['value']}: {o['label']}" for o in q["options"]))
                answer = await asyncio.to_thread(input, "Answer (or skip): ")
                response = await client.post(
                    f"/api/searches/{search_id}/question-answer",
                    json={"question_id": q["id"], "value": answer or "skip"},
                )
                if response.is_error:
                    print(response.text)
            elif state["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                report = (await client.get(f"/api/searches/{search_id}/report")).json()
                print(json.dumps(report, indent=2))
                return
            await asyncio.sleep(1)
        raise TimeoutError("Search remains stored; inspect its ID in the API")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    asyncio.run(search(parser.parse_args()))
