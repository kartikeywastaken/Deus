"""Isolated GHunt runner using only metadata lookup, never max_details or private names."""

import asyncio
import contextlib
import io
import json
import sys


async def lookup(email):
    try:
        from ghunt.apis.peoplepa import PeoplePaHttp
        from ghunt.helpers import auth
        from ghunt.helpers.utils import get_httpx_client
    except ImportError:
        return {
            "status": "UNAVAILABLE",
            "message": "Install ghunt==2.3.4 in GHUNT_PYTHON environment",
        }
    try:
        async with get_httpx_client() as client:
            async with asyncio.timeout(20):
                creds = await auth.load_and_auth(client)
                found, target = await PeoplePaHttp(creds).people_lookup(
                    client, email, params_template="just_gaia_id"
                )
        if not found or "PROFILE" not in target.sourceIds:
            return {"status": "NO_RESULTS"}
        return {"status": "SUCCESS", "gaia_id": str(target.personId)}
    except (EOFError, SystemExit):
        return {
            "status": "AUTH_REQUIRED",
            "message": "Run ghunt login in the configured environment",
        }
    except Exception as exc:
        return {"status": "FAILED", "message": type(exc).__name__}


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()):
        result = asyncio.run(lookup(sys.argv[1]))
    print(json.dumps(result))
