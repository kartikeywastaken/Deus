"""High-performance public email service enumeration adapter (Holehe-style passive checks)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from ..base_source import BaseEmailSource
from ..schemas import DiscoveredIdentifier, EmailSourceResult, EmailSourceStatus


class ServiceChecker:
    name: str
    category: str = "social"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        raise NotImplementedError


class SpotifyChecker(ServiceChecker):
    name = "spotify"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = "https://spclient.wg.spotify.com/signup/public/v1/account"
        params = {"validate": "1", "email": email}
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            res = await client.get(url, params=params, headers=headers, timeout=4.0)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == 20:
                    return {"exists": True, "confidence": 0.95, "canonical_url": "https://spotify.com", "display_name": "Spotify Account"}
                if data.get("status") == 1:
                    return {"exists": False}
        except Exception:
            pass
        return {"exists": None}


class ImgurChecker(ServiceChecker):
    name = "imgur"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = "https://api.imgur.com/account/v1/accounts/email"
        data = {"email": email}
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            res = await client.post(url, data=data, headers=headers, timeout=4.0)
            if res.status_code == 200:
                data_json = res.json()
                if data_json.get("data", {}).get("available") is False:
                    return {"exists": True, "confidence": 0.90, "canonical_url": "https://imgur.com", "display_name": "Imgur Account"}
                return {"exists": False}
        except Exception:
            pass
        return {"exists": None}


class ChessComChecker(ServiceChecker):
    name = "chess.com"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = f"https://www.chess.com/callback/email/available?email={email}"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            res = await client.get(url, headers=headers, timeout=4.0)
            if res.status_code == 200:
                data = res.json()
                if data.get("available") is False:
                    return {"exists": True, "confidence": 0.92, "canonical_url": "https://chess.com", "display_name": "Chess.com Account"}
                return {"exists": False}
        except Exception:
            pass
        return {"exists": None}


class DuolingoChecker(ServiceChecker):
    name = "duolingo"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = f"https://www.duolingo.com/2017-06-30/users?email={email}"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            res = await client.get(url, headers=headers, timeout=4.0)
            if res.status_code == 200:
                users = res.json().get("users", [])
                if users:
                    u = users[0]
                    username = u.get("username")
                    name = u.get("name")
                    return {
                        "exists": True,
                        "confidence": 0.98,
                        "username": username,
                        "display_name": name or "Duolingo Learner",
                        "canonical_url": f"https://duolingo.com/profile/{username}" if username else "https://duolingo.com",
                    }
                return {"exists": False}
        except Exception:
            pass
        return {"exists": None}


class AdobeChecker(ServiceChecker):
    name = "adobe"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = "https://auth.services.adobe.com/signin/v2/users/all"
        data = {"username": email}
        headers = {"User-Agent": "Mozilla/5.0", "X-IMS-CLIENT-ID": "adobedotcom2"}
        try:
            res = await client.post(url, json=data, headers=headers, timeout=4.0)
            if res.status_code == 200:
                data_json = res.json()
                if any(item.get("status") == "EXISTS" for item in data_json.get("users", [])):
                    return {"exists": True, "confidence": 0.95, "canonical_url": "https://adobe.com", "display_name": "Adobe Creative Cloud"}
                return {"exists": False}
        except Exception:
            pass
        return {"exists": None}


class GravatarChecker(ServiceChecker):
    name = "gravatar"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        import hashlib
        email_hash = hashlib.md5(email.strip().lower().encode('utf-8')).hexdigest()
        url = f"https://www.gravatar.com/{email_hash}.json"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            res = await client.get(url, headers=headers, timeout=4.0)
            if res.status_code == 200:
                data = res.json()
                entry = data.get("entry", [{}])[0]
                username = entry.get("preferredUsername")
                display_name = entry.get("displayName") or entry.get("name", {}).get("formatted")
                profile_url = entry.get("profileUrl") or f"https://gravatar.com/{email_hash}"
                return {
                    "exists": True,
                    "confidence": 0.99,
                    "username": username,
                    "display_name": display_name or "Gravatar Global Profile",
                    "canonical_url": profile_url
                }
            elif res.status_code == 404:
                return {"exists": False}
        except Exception:
            pass
        return {"exists": None}


class GitHubEmailChecker(ServiceChecker):
    name = "github"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        url = f"https://api.github.com/search/users?q={email}+in:email"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github.v3+json"}
        try:
            res = await client.get(url, headers=headers, timeout=4.0)
            if res.status_code == 200:
                data = res.json()
                items = data.get("items", [])
                if items:
                    u = items[0]
                    username = u.get("login")
                    return {
                        "exists": True,
                        "confidence": 0.99,
                        "username": username,
                        "display_name": username,
                        "canonical_url": f"https://github.com/{username}"
                    }
                return {"exists": False}
        except Exception:
            pass
        return {"exists": None}


class RequestChecker(ServiceChecker):
    """Declarative checker: one request per site, then interpret the response.

    ``interpret`` returns ``True`` when the email is registered, ``False`` when the
    endpoint explicitly reports the address as free, and ``None`` when the site
    cannot be verified passively (auth-gated, changed, or blocked). Returning
    ``None`` keeps the operator honest instead of guessing ownership.
    """

    name = ""
    category = "social"
    label = ""
    url = ""
    method = "GET"
    canonical_url = ""
    display_name = ""
    confidence = 0.85
    extra_headers: dict[str, str] = {}

    def request(self, email: str) -> dict[str, Any]:
        return {}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        return None

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)", **self.extra_headers}
        try:
            res = await client.request(
                self.method, self.url, headers=headers, timeout=4.0, **self.request(email)
            )
            try:
                payload = res.json()
            except Exception:
                payload = None
            verdict = self.interpret(res.status_code, res.text, payload)
            if verdict is True:
                return {
                    "exists": True,
                    "confidence": self.confidence,
                    "canonical_url": self.canonical_url,
                    "display_name": self.display_name,
                }
            if verdict is False:
                return {"exists": False}
        except Exception:
            pass
        return {"exists": None}


class InstagramChecker(RequestChecker):
    name = "instagram"
    label = "Instagram"
    url = "https://www.instagram.com/api/v1/web/accounts/web_create_ajax/attempt/"
    method = "POST"
    canonical_url = "https://www.instagram.com/"
    display_name = "Instagram Account"
    extra_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/accounts/emailsignup/",
    }

    def request(self, email: str) -> dict[str, Any]:
        return {"data": {"email": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        if "email_is_taken" in text:
            return True
        if "invalid_email" in text or "email_shrinked" in text:
            return False
        return None


class PinterestChecker(RequestChecker):
    name = "pinterest"
    label = "Pinterest"
    url = "https://www.pinterest.com/resource/EmailExistsResource/get/"
    canonical_url = "https://www.pinterest.com/"
    display_name = "Pinterest Account"
    extra_headers = {"Accept": "application/json, text/javascript, */*; q=0.01"}

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"source_url": "/", "data": json.dumps({"options": {"email": email}})}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        if status_code != 200 or not isinstance(payload, dict):
            return None
        data = (payload.get("resource_response") or {}).get("data")
        if data not in (None, False, [], {}):
            return True
        return False


class TwitterChecker(RequestChecker):
    name = "twitter"
    label = "X (Twitter)"
    url = "https://api.twitter.com/i/users/email_available.json"
    canonical_url = "https://twitter.com/"
    display_name = "X (Twitter) Account"

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"email": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        if not isinstance(payload, dict):
            return None
        if payload.get("valid") is False or payload.get("taken") is True:
            return True
        if payload.get("valid") is True:
            return False
        return None


class RedditChecker(RequestChecker):
    name = "reddit"
    label = "Reddit"
    url = "https://www.reddit.com/api/register/check_email.json"
    method = "POST"
    canonical_url = "https://www.reddit.com/"
    display_name = "Reddit Account"

    def request(self, email: str) -> dict[str, Any]:
        return {"data": {"email": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        if not isinstance(payload, dict):
            return None
        if payload.get("available") is False or payload.get("error") == "EMAIL_TAKEN":
            return True
        if payload.get("available") is True:
            return False
        return None


class LinkedInChecker(RequestChecker):
    name = "linkedin"
    label = "LinkedIn"
    url = "https://www.linkedin.com/checkpoint/rp/request-password-reset-submit"
    method = "POST"
    canonical_url = "https://www.linkedin.com/"
    display_name = "LinkedIn Account"
    confidence = 0.6

    def request(self, email: str) -> dict[str, Any]:
        return {"data": {"session_key": email, "csrftoken": "ajax:0"}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "no account" in lowered or "couldn't find" in lowered or "not found" in lowered:
            return False
        if status_code == 200 and "password" in lowered and "reset" in lowered:
            return True
        return None


class SnapchatChecker(RequestChecker):
    name = "snapchat"
    label = "Snapchat"
    url = "https://accounts.snapchat.com/accounts/get_username_suggestions"
    method = "POST"
    canonical_url = "https://www.snapchat.com/"
    display_name = "Snapchat Account"
    confidence = 0.7
    extra_headers = {"Content-Type": "application/json"}

    def request(self, email: str) -> dict[str, Any]:
        return {"json": {"email": email, "requested_username": "deus_probe"}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if status_code == 200 and "email" in lowered and "already" in lowered:
            return True
        return None


class FacebookChecker(RequestChecker):
    name = "facebook"
    label = "Facebook"
    url = "https://www.facebook.com/ajax/login/help/identify.php"
    method = "POST"
    canonical_url = "https://www.facebook.com/"
    display_name = "Facebook Account"
    confidence = 0.6
    extra_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.facebook.com/login/identify/",
    }

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"ctx": "recover"}, "data": {"email": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "no account" in lowered or "couldn't find" in lowered or "invalid username" in lowered:
            return False
        if "password" in lowered or "code" in lowered:
            return True
        return None


class AmazonChecker(RequestChecker):
    name = "amazon"
    label = "Amazon"
    url = "https://www.amazon.com/ap/register"
    canonical_url = "https://www.amazon.com/"
    display_name = "Amazon Account"
    confidence = 0.7
    extra_headers = {"Accept": "text/html,application/xhtml+xml"}

    def request(self, email: str) -> dict[str, Any]:
        return {
            "params": {
                "openid.pape.max_auth_age": "0",
                "openid.return_to": "https://www.amazon.com/",
                "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
                "openid.assoc_handle": "usflex",
                "openid.mode": "checkid_setup",
                "openid.ns": "http://specs.openid.net/auth/2.0",
                "prepopulatedLoginId": email,
                "failedSignInCount": "0",
            }
        }

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "account already exists" in lowered:
            return True
        if "create account" in lowered or "ap_register" in lowered:
            return False
        return None


class WordpressChecker(RequestChecker):
    name = "wordpress"
    label = "WordPress.com"
    url = "https://public-api.wordpress.com/rest/v1.1/users/{email}/auth-options"
    canonical_url = "https://wordpress.com/"
    display_name = "WordPress.com Account"

    async def check(self, email: str, client: httpx.AsyncClient) -> dict[str, Any]:
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            res = await client.get(self.url.format(email=email), headers=headers, timeout=4.0)
            if res.status_code == 200:
                return {
                    "exists": True,
                    "confidence": self.confidence,
                    "canonical_url": self.canonical_url,
                    "display_name": self.display_name,
                }
            if res.status_code in (400, 404):
                return {"exists": False}
        except Exception:
            pass
        return {"exists": None}


class FirefoxChecker(RequestChecker):
    name = "firefox"
    label = "Firefox Accounts"
    url = "https://api.accounts.firefox.com/v1/account/login"
    method = "POST"
    canonical_url = "https://accounts.firefox.com/"
    display_name = "Firefox Account"
    confidence = 0.8
    extra_headers = {"Content-Type": "application/json"}

    def request(self, email: str) -> dict[str, Any]:
        return {
            "json": {
                "email": email,
                "authPW": "0" * 64,
            }
        }

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "unknown account" in lowered or "account not found" in lowered:
            return False
        if status_code in (200, 400) and ("password" in lowered or "incorrect" in lowered):
            return True
        return None


class TumblrChecker(RequestChecker):
    name = "tumblr"
    label = "Tumblr"
    url = "https://www.tumblr.com/svc/account/register"
    method = "POST"
    canonical_url = "https://www.tumblr.com/"
    display_name = "Tumblr Account"
    confidence = 0.75

    def request(self, email: str) -> dict[str, Any]:
        return {
            "data": {
                "email": email,
                "password": "deus-probe-not-a-real-password",
                "tumblelog": "deusprobe",
            }
        }

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "already_using_email" in lowered or "email already" in lowered:
            return True
        if "registration" in lowered or "success" in lowered:
            return False
        return None


class LastfmChecker(RequestChecker):
    name = "lastfm"
    label = "Last.fm"
    url = "https://www.last.fm/join/complete"
    canonical_url = "https://www.last.fm/"
    display_name = "Last.fm Account"
    confidence = 0.7

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"email": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "already" in lowered and "email" in lowered:
            return True
        if "join" in lowered or "create" in lowered:
            return False
        return None


class TwitchChecker(RequestChecker):
    name = "twitch"
    label = "Twitch"
    url = "https://passport.twitch.tv/register"
    method = "POST"
    canonical_url = "https://www.twitch.tv/"
    display_name = "Twitch Account"
    confidence = 0.7
    extra_headers = {"Content-Type": "application/json"}

    def request(self, email: str) -> dict[str, Any]:
        return {
            "json": {
                "email": email,
                "password": "deus-probe-not-a-real-password",
                "username": "deusprobe",
            }
        }

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = json.dumps(payload or {}, default=str).lower()
        if "already" in lowered and "email" in lowered:
            return True
        if status_code in (200, 201):
            return False
        return None


class VimeoChecker(RequestChecker):
    name = "vimeo"
    label = "Vimeo"
    url = "https://vimeo.com/join"
    canonical_url = "https://vimeo.com/"
    display_name = "Vimeo Account"
    confidence = 0.65

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"email": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "already" in lowered and "email" in lowered:
            return True
        if "join" in lowered or "sign up" in lowered:
            return False
        return None


class StravaChecker(RequestChecker):
    name = "strava"
    label = "Strava"
    url = "https://www.strava.com/api/v3/auth/password/strength"
    canonical_url = "https://www.strava.com/"
    display_name = "Strava Account"
    confidence = 0.65

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"email": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "already" in lowered and "email" in lowered:
            return True
        return None


class SoundcloudChecker(RequestChecker):
    name = "soundcloud"
    label = "SoundCloud"
    url = "https://soundcloud.com/signup"
    canonical_url = "https://soundcloud.com/"
    display_name = "SoundCloud Account"
    confidence = 0.65

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"email": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "already" in lowered and "email" in lowered:
            return True
        return None


class TiktokChecker(RequestChecker):
    name = "tiktok"
    label = "TikTok"
    url = "https://www.tiktok.com/api/v1/user/email/check/"
    canonical_url = "https://www.tiktok.com/"
    display_name = "TikTok Account"
    confidence = 0.7

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"email": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data") or {}
        if data.get("exists") is True or data.get("is_registered") is True:
            return True
        if data.get("exists") is False or data.get("is_registered") is False:
            return False
        return None


class MicrosoftChecker(RequestChecker):
    name = "microsoft"
    label = "Microsoft / Outlook"
    url = "https://signup.live.com/API/CheckAvailableSigninNames"
    canonical_url = "https://outlook.live.com/"
    display_name = "Microsoft Account"
    confidence = 0.7
    extra_headers = {"Content-Type": "application/json", "Accept": "application/json"}

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"api-version": "2.0", "uas": "0"}, "json": {"signInName": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        if status_code == 200 and isinstance(payload, dict):
            if "isAvailable" in payload:
                return payload.get("isAvailable") is False
            if payload.get("error"):
                return True
        return None


class YahooChecker(RequestChecker):
    name = "yahoo"
    label = "Yahoo"
    url = "https://login.yahoo.com/account/module/create"
    canonical_url = "https://login.yahoo.com/"
    display_name = "Yahoo Account"
    confidence = 0.6

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"validateField": "userId", "userId": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "already" in lowered and ("taken" in lowered or "exists" in lowered):
            return True
        return None


class EbayChecker(RequestChecker):
    name = "ebay"
    label = "eBay"
    url = "https://www.ebay.com/signin/register"
    canonical_url = "https://www.ebay.com/"
    display_name = "eBay Account"
    confidence = 0.6

    def request(self, email: str) -> dict[str, Any]:
        return {"params": {"email": email}}

    def interpret(self, status_code: int, text: str, payload: Any) -> bool | None:
        lowered = text.lower()
        if "already" in lowered and "email" in lowered:
            return True
        return None


PUBLIC_CHECKERS = [
    # Core, stable account checks (username/details are extracted when available).
    SpotifyChecker(),
    ImgurChecker(),
    ChessComChecker(),
    DuolingoChecker(),
    AdobeChecker(),
    GravatarChecker(),
    GitHubEmailChecker(),
    # Wider site coverage: each returns True/False/None so the UI can show every
    # site the email was checked against, not only the positive hits.
    InstagramChecker(),
    PinterestChecker(),
    TwitterChecker(),
    RedditChecker(),
    LinkedInChecker(),
    SnapchatChecker(),
    FacebookChecker(),
    AmazonChecker(),
    WordpressChecker(),
    FirefoxChecker(),
    TumblrChecker(),
    LastfmChecker(),
    TwitchChecker(),
    VimeoChecker(),
    StravaChecker(),
    SoundcloudChecker(),
    TiktokChecker(),
    MicrosoftChecker(),
    YahooChecker(),
    EbayChecker(),
]


class HolehePublicAdapter(BaseEmailSource):
    name = "holehe_public"
    category = "enumeration"
    cost = 2
    expected_latency_ms = 800
    reliability = 0.92
    priority = 15

    async def check(self, email: str, context: dict[str, Any] | None = None) -> EmailSourceResult:
        start = time.monotonic()
        client: httpx.AsyncClient = context.get("client") if context else None
        own_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=5.0)
            own_client = True

        found_services = []
        identifiers = []
        evidence = {}
        site_status: dict[str, Any] = {}

        try:
            tasks = [checker.check(email, client) for checker in PUBLIC_CHECKERS]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for checker, res in zip(PUBLIC_CHECKERS, results, strict=True):
                entry = res if isinstance(res, dict) else {"exists": None}
                exists = entry.get("exists")
                default_label = checker.name.replace("_", " ").title()
                site_status[checker.name] = {
                    "label": getattr(checker, "label", "") or default_label,
                    "exists": exists,
                    "confidence": entry.get("confidence"),
                    "username": entry.get("username"),
                    "display_name": entry.get("display_name"),
                    "canonical_url": entry.get("canonical_url"),
                }
                if exists is True:
                    found_services.append(checker.name)
                    evidence[checker.name] = entry
                    conf = entry.get("confidence", 0.85)

                    username = entry.get("username")
                    if username:
                        identifiers.append(
                            DiscoveredIdentifier(
                                type="username",
                                value=username,
                                normalized_value=username.casefold(),
                                source=f"{self.name}:{checker.name}",
                                confidence=conf,
                                metadata={"platform": checker.name},
                            )
                        )
                    canonical = entry.get("canonical_url")
                    if canonical:
                        identifiers.append(
                            DiscoveredIdentifier(
                                type="profile_url",
                                value=canonical,
                                normalized_value=canonical.casefold(),
                                source=f"{self.name}:{checker.name}",
                                confidence=conf,
                            )
                        )

            duration = (time.monotonic() - start) * 1000
            if found_services:
                return self._result(
                    EmailSourceStatus.FOUND,
                    account_exists=True,
                    confidence=0.95,
                    identifiers=identifiers,
                    evidence={
                        "found_services": found_services,
                        "details": evidence,
                        "site_status": site_status,
                    },
                    response_time_ms=duration,
                    message=f"Registered accounts found on: {', '.join(found_services)}",
                )
            return self._result(
                EmailSourceStatus.NOT_FOUND,
                evidence={"found_services": [], "details": {}, "site_status": site_status},
                response_time_ms=duration,
            )
        except Exception as exc:
            return self._result(
                EmailSourceStatus.ERROR,
                message=str(exc),
                response_time_ms=(time.monotonic() - start) * 1000,
            )
        finally:
            if own_client:
                await client.aclose()
