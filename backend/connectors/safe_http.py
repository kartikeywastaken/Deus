"""Bounded HTTPS fetches; DNS answers are validated and pinned to the connection."""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import aiohttp


def validate_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or len(value) > 2000
    ):
        raise ValueError("Only public HTTPS URLs on port 443 without credentials are allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local destinations are forbidden")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return value
    if not address.is_global:
        raise ValueError("Non-public IP addresses are forbidden")
    return value


class PublicResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        entries = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM
        )
        results = []
        for af, _, proto, _, address in entries:
            ip = address[0]
            if not ipaddress.ip_address(ip).is_global:
                raise ValueError("DNS resolved to a non-public destination")
            results.append(
                dict(
                    hostname=host,
                    host=ip,
                    port=port,
                    family=af,
                    proto=proto,
                    flags=socket.AI_NUMERICHOST,
                )
            )
        return results

    async def close(self):
        pass


async def fetch_public(url, *, max_bytes=1_000_000, allowed_types=("text/html",)):
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=12),
        trust_env=False,
        cookie_jar=aiohttp.DummyCookieJar(),
        auto_decompress=False,
        headers={"User-Agent": "Deus-public-profile-research/0.2", "Accept-Encoding": "identity"},
    ) as client:
        for _ in range(3):
            validate_url(url)
            async with client.get(url, allow_redirects=False) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                if response.status != 200:
                    raise ValueError(f"Public source HTTP {response.status}")
                if response.content_type not in allowed_types:
                    raise ValueError("Unsupported response content type")
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise ValueError("Compressed responses are not accepted")
                data = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise ValueError("Public source exceeds the byte limit")
                return bytes(data), str(response.url), response.content_type
        raise ValueError("Redirect limit exceeded")
