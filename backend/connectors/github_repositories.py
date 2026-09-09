"""Read bounded public repository context. References never assert ownership."""

import asyncio
import base64
import re

from .profile_links import profile_link
from .schemas import ObservationArtifact


def readme_links(text):
    return list(dict.fromkeys(re.findall(r'https://[^\s<>"\)\]]+', text)))[:50]


async def repository_context(client, username, profile_url):
    observations, errors = [], []
    count = 1
    response = await client.get(
        f"https://api.github.com/users/{username}/repos",
        params={"per_page": 3, "sort": "updated", "type": "owner"},
    )
    if response.status_code != 200:
        return [], count, [f"Repository list HTTP {response.status_code}"]
    repos = response.json()
    if not isinstance(repos, list):
        return [], count, ["Invalid repository list"]
    selected = [
        r
        for r in repos
        if not r.get("fork")
        and r.get("owner", {}).get("login", "").casefold() == username.casefold()
    ][:3]
    # Include the profile README even when it is not among recently updated repos.
    names = list(dict.fromkeys([username] + [r["name"] for r in selected]))[:4]

    async def read(name):
        if not re.fullmatch(r"[\w.-]{1,100}", name):
            return None
        return await client.get(f"https://api.github.com/repos/{username}/{name}/readme")

    responses = await asyncio.gather(*(read(name) for name in names), return_exceptions=True)
    count += len(names)
    for response in responses:
        if response is None:
            continue
        if isinstance(response, Exception):
            errors.append(type(response).__name__)
            continue
        if response.status_code == 404:
            continue
        if response.status_code != 200:
            errors.append(f"README HTTP {response.status_code}")
            continue
        raw = response.json()
        if raw.get("encoding") != "base64" or raw.get("size", 0) > 200_000:
            errors.append("README exceeds supported encoding/size")
            continue
        content = base64.b64decode(raw.get("content", "")).decode("utf-8", errors="replace")
        for link in readme_links(content):
            if profile_link(link):
                observations.append(
                    ObservationArtifact(
                        signal_type="REPOSITORY_SOCIAL_REFERENCE",
                        value=link,
                        reliability=0.5,
                        profile_url=profile_url,
                        source_url=raw.get("html_url") or str(response.url),
                        raw_data={
                            "attribution": "UNVERIFIED_REFERENCE",
                            "identity_evidence": False,
                        },
                    )
                )
    return observations, count, errors
