"""Isolated, pinned Osintgram get_user bridge. No login, contacts or social graph crawl."""

import codecs
import contextlib
import hashlib
import io
import json
import re
import ssl
import sys
from pathlib import Path

UPSTREAM_COMMIT = "c8ba1f0ae119c7def2e2ff8cf694a85b2ca49be0"
HASHES = {
    "Osintgram.py": "3572661615c51ed4eafdd49ffb1db993977c22c18f192bb35eeda2e6a4f0639a",
    "config.py": "711a8ab0457581e79998ae5a0c6db5b03708ea07541afa601030b47b07e76a71",
    "printcolors.py": "ab8346f4f0d073199ae415a5e47df9b15638daf88b74801284b42c136c289495",
}


def load_upstream(source):
    root = Path(source).resolve()
    if (root / "src/__init__.py").exists():
        raise ValueError("Unreviewed package initializer")
    for name, expected in HASHES.items():
        if hashlib.sha256((root / "src" / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Osintgram source differs from reviewed pin")
    sys.path.insert(0, str(root))
    verified_context = ssl._create_default_https_context
    try:
        from src.Osintgram import Osintgram
    finally:
        # Upstream disables TLS verification on import. Never retain that change.
        ssl._create_default_https_context = verified_context
    return Osintgram


def public_fields(user, requested):
    if not isinstance(user, dict) or user.get("username", "").casefold() != requested.casefold():
        raise ValueError("Unexpected profile response")
    if user.get("is_private") is not False:
        return {
            "status": "PARTIAL",
            "message": "Private or unknown visibility; no fields collected.",
        }
    keys = ("pk", "username", "full_name", "biography", "external_url", "bio_links", "is_private")
    safe = {k: user[k] for k in keys if k in user}
    # Do not pass arbitrary nested provider data through the bridge.
    safe["bio_links"] = [
        {"url": item["url"]}
        for item in user.get("bio_links", [])[:20]
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    ]
    return {"status": "SUCCESS", "user": safe}


class LookupProblem(Exception):
    def __init__(self, status):
        self.status = status


def collect(source, session_path, username):
    if not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", username):
        raise ValueError("Invalid Instagram username")
    Osintgram = load_upstream(source)
    from instagram_private_api import Client, ClientError

    path = Path(session_path)
    if path.stat().st_size > 100_000 or path.stat().st_mode & 0o077:
        raise ValueError("Session file must be private (0600) and under 100 KB")

    def decode(value):
        if value.get("__class__") == "bytes":
            return codecs.decode(value["__value__"].encode(), "base64")
        return value

    session = json.loads(path.read_text(), object_hook=decode)
    if not session.get("cookie"):
        raise LookupProblem("AUTH_REQUIRED")

    class ReadOnlyClient(Client):
        calls = 0
        observed_user = None

        def login(self):
            raise LookupProblem("AUTH_REQUIRED")

        def _call_api(self, endpoint, *args, **kwargs):
            if endpoint != f"users/{username}/usernameinfo/" or self.calls or args or kwargs:
                raise ValueError("Non-allowlisted Osintgram operation")
            self.calls += 1
            try:
                result = super()._call_api(endpoint)
            except ClientError as exc:
                raise LookupProblem(
                    "RATE_LIMITED"
                    if exc.code == 429
                    else "PARTIAL"
                    if exc.code == 404
                    else "AUTH_REQUIRED"
                ) from None
            self.observed_user = result.get("user")
            return result

    api = ReadOnlyClient("", "", settings=session, timeout=10, auto_patch=False)
    if not api.authenticated_user_id:
        raise LookupProblem("AUTH_REQUIRED")
    # Bypass constructor: it logs in, checks follow relationships and writes files.
    tool = object.__new__(Osintgram)
    tool.api, tool.writeFile = api, False
    tool.get_user(username)
    return public_fields(api.observed_user, username)


def main():
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if len(sys.argv) == 3 and sys.argv[1] == "--check":
                load_upstream(sys.argv[2])
                result = {
                    "status": "READY",
                    "commit": UPSTREAM_COMMIT,
                    "tls_verification": ssl._create_default_https_context().check_hostname,
                }
            else:
                result = collect(*sys.argv[1:])
    except LookupProblem as exc:
        result = {"status": exc.status, "message": "Provider requires valid access or retry later."}
    except (Exception, SystemExit) as exc:
        result = {
            "status": "AUTH_REQUIRED"
            if type(exc).__name__
            in {
                "ClientCookieExpiredError",
                "ClientLoginRequiredError",
                "ClientCheckpointRequiredError",
            }
            else "FAILED",
            "message": type(exc).__name__,
        }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
