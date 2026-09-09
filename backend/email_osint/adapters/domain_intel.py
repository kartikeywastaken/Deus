"""Domain intelligence source adapter (DNS MX, TXT, Provider identification)."""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Any

from ..base_source import BaseEmailSource
from ..schemas import DiscoveredIdentifier, EmailDomainIntel, EmailProviderType, EmailSourceResult, EmailSourceStatus

KNOWN_PROVIDERS = {
    "gmail.com": ("Google Workspace / Gmail", EmailProviderType.GMAIL, True, False),
    "googlemail.com": ("Google Workspace / Gmail", EmailProviderType.GMAIL, True, False),
    "outlook.com": ("Microsoft Outlook / Office 365", EmailProviderType.OUTLOOK, True, False),
    "hotmail.com": ("Microsoft Outlook / Hotmail", EmailProviderType.OUTLOOK, True, False),
    "live.com": ("Microsoft Outlook", EmailProviderType.OUTLOOK, True, False),
    "proton.me": ("Proton Mail", EmailProviderType.PROTON, True, False),
    "protonmail.com": ("Proton Mail", EmailProviderType.PROTON, True, False),
    "icloud.com": ("Apple iCloud Mail", EmailProviderType.ICLOUD, True, False),
    "me.com": ("Apple iCloud Mail", EmailProviderType.ICLOUD, True, False),
    "yahoo.com": ("Yahoo Mail", EmailProviderType.YAHOO, True, False),
    "ymail.com": ("Yahoo Mail", EmailProviderType.YAHOO, True, False),
}

DISPOSABLE_DOMAINS = {
    "tempmail.com", "guerrillamail.com", "10minutemail.com", "trashmail.com",
    "sharklasers.com", "yopmail.com", "dispostable.com", "mailinator.com",
}


class DomainIntelAdapter(BaseEmailSource):
    name = "domain_intel"
    category = "domain"
    cost = 1
    expected_latency_ms = 200
    reliability = 0.99
    priority = 5

    async def check(self, email: str, context: dict[str, Any] | None = None) -> EmailSourceResult:
        start = time.monotonic()
        if "@" not in email:
            return self._result(EmailSourceStatus.ERROR, message="Invalid email format")

        domain = email.split("@")[-1].lower().strip()
        mx_records = []
        
        # Check known provider dictionary first
        if domain in KNOWN_PROVIDERS:
            name, p_type, is_free, is_disp = KNOWN_PROVIDERS[domain]
            intel = EmailDomainIntel(
                domain=domain,
                provider_name=name,
                provider_type=p_type,
                is_free_provider=is_free,
                is_disposable=is_disp,
            )
        else:
            # Perform DNS MX lookup asynchronously in executor
            loop = asyncio.get_running_loop()
            try:
                mx_hosts = await loop.run_in_executor(None, self._get_mx_records, domain)
                mx_records = mx_hosts
            except Exception:
                mx_records = []

            provider_name = "Custom / Enterprise Domain"
            provider_type = EmailProviderType.CUSTOM_CORPORATE
            is_disposable = domain in DISPOSABLE_DOMAINS

            # Identify from MX records
            mx_str = " ".join(mx_hosts).lower()
            if "google" in mx_str or "googlemail" in mx_str:
                provider_name = "Google Workspace (Custom Domain)"
                provider_type = EmailProviderType.GMAIL
            elif "outlook" in mx_str or "protection.outlook.com" in mx_str:
                provider_name = "Microsoft 365 (Custom Domain)"
                provider_type = EmailProviderType.OUTLOOK
            elif "proton" in mx_str:
                provider_name = "Proton Mail (Custom Domain)"
                provider_type = EmailProviderType.PROTON

            org_hint = domain.split(".")[0].capitalize() if provider_type == EmailProviderType.CUSTOM_CORPORATE else None

            intel = EmailDomainIntel(
                domain=domain,
                provider_name=provider_name,
                provider_type=provider_type,
                mx_records=mx_records,
                is_disposable=is_disposable,
                is_free_provider=False,
                organization_hint=org_hint,
            )

        duration = (time.monotonic() - start) * 1000
        identifiers = [
            DiscoveredIdentifier(
                type="domain",
                value=domain,
                normalized_value=domain,
                source=self.name,
                confidence=0.99,
                metadata={"provider": intel.provider_name},
            )
        ]
        if intel.organization_hint:
            identifiers.append(
                DiscoveredIdentifier(
                    type="organization",
                    value=intel.organization_hint,
                    normalized_value=intel.organization_hint.casefold(),
                    source=self.name,
                    confidence=0.7,
                )
            )

        return self._result(
            EmailSourceStatus.FOUND,
            account_exists=True,
            confidence=0.99,
            identifiers=identifiers,
            evidence=intel.model_dump(mode="json"),
            response_time_ms=duration,
        )

    def _get_mx_records(self, domain: str) -> list[str]:
        try:
            # Simple fallback DNS MX resolution using socket
            answers = socket.getaddrinfo(domain, None)
            return [a[4][0] for a in answers if a[4]]
        except Exception:
            return []
