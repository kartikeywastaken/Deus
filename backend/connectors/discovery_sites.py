"""Reviewed public platforms; resolve exact names against installed tool databases."""

import importlib.util
import json
from pathlib import Path

SITES = (
    "GitHub",
    "Reddit",
    "Dev.to",
    "Twitter",
    "Instagram",
    "LinkedIn",
    "HackerNews",
    "Medium",
    "GitLab",
    "Mastodon",
    "Telegram",
    "YouTube",
    "TikTok",
    "Pinterest",
    "Tumblr",
    "Keybase",
    "Steam",
    "Twitch",
    "StackOverflow",
    "Pastebin",
    "Facebook",
    "Bluesky",
    "Threads",
    "SoundCloud",
    "Spotify",
    "Behance",
    "Dribbble",
    "Codepen",
    "Replit",
    "last.fm",
)


def site_database(tool):
    module = "maigret" if tool == "maigret" else "sherlock_project"
    spec = importlib.util.find_spec(module)
    if not spec or not spec.origin:
        return {}, [], list(SITES)
    path = Path(spec.origin).parent / "resources/data.json"
    if not path.exists():
        return {}, [], list(SITES)
    raw = json.loads(path.read_text())
    entries = raw.get("sites", raw)
    index = {name.casefold(): name for name in entries}
    names, missing = [], []
    for name in SITES:
        key = {"Dev.to": "dev community", "Mastodon": "mastodon.social"}.get(name, name.casefold())
        if name == "Replit" and tool == "sherlock":
            key = "replit.com"
        if key in index:
            names.append(index[key])
        else:
            missing.append(name)
    return raw, names, missing


def check_details(rows):
    results = []
    for row in rows:
        reason = row.get("error_reason", "").lower()
        code = str(row.get("http_status", ""))
        state = row.get("exists", "").lower()
        if state == "claimed":
            status = "FOUND"
        elif state in {"available", "unclaimed"}:
            status = "NOT_FOUND"
        elif "captcha" in reason or "bot protection" in reason:
            status = "BLOCKED"
        elif "rate limit" in reason or code == "429":
            status = "RATE_LIMITED"
        elif code in {"401", "403"}:
            status = "ACCESS_RESTRICTED"
        elif "timeout" in reason:
            status = "TIMEOUT"
        else:
            status = "INCONCLUSIVE"
        results.append({"site": row.get("name"), "status": status, "http_status": code})
    return results
