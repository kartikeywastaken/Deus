"""Explicit integration boundaries, not implementations masquerading as live tools."""

from .base import BaseConnector
from .schemas import ConnectorCapabilities, ConnectorInputType, ConnectorRunStatus


class RestrictedConnector(BaseConnector):
    def __init__(self, name, status, reason, url, input_type):
        super().__init__()
        self.name, self.live_status = name, ConnectorRunStatus(status)
        self.live_message, self.documentation_url = reason, url
        self.capabilities = ConnectorCapabilities(
            accepted_inputs=frozenset({ConnectorInputType(input_type)}),
            produced_artifacts=frozenset(),
            supports_discovery=False,
            requires_auth=status == "AUTH_REQUIRED",
            is_manual=status == "MANUAL",
        )

    async def discover(self, connector_input):
        return self._unavailable()


def restricted_connectors():
    specs = [
        (
            "email2phonenumber",
            "DISABLED",
            "Not integrated: account-recovery probing for non-public phone numbers is excluded.",
            "https://github.com/martinvigo/email2phonenumber",
            "EMAIL",
        ),
        (
            "ghunt",
            "AUTH_REQUIRED",
            "Requires operator authentication; no cookie access or automated adapter configured.",
            "https://github.com/mxrch/GHunt",
            "EMAIL",
        ),
        (
            "osintgram",
            "AUTH_REQUIRED",
            "Requires Instagram credentials or token; no authenticated adapter configured.",
            "https://github.com/Datalux/Osintgram",
            "INSTAGRAM_PROFILE",
        ),
        (
            "instagram_osint",
            "UNAVAILABLE",
            "Upstream repository is archived; live compatibility is not established.",
            "https://github.com/sc1341/InstagramOSINT",
            "USERNAME",
        ),
        (
            "linkedint",
            "MANUAL",
            "Interactive credential-dependent upstream; no unattended integration configured.",
            "https://github.com/vysecurity/LinkedInt",
            "NAME",
        ),
        (
            "phoneinfoga",
            "DISABLED",
            "Phone collection is disabled; no phone-seed adapter is implemented.",
            "https://sundowndev.github.io/phoneinfoga/",
            "PHONE",
        ),
        (
            "peekyou",
            "MANUAL",
            "No supported automated interface has been verified; manual source review only.",
            "https://www.peekyou.com/",
            "NAME",
        ),
        (
            "facecheck",
            "DISABLED",
            "Facial identification is not supported by this project.",
            "https://facecheck.id/en/Face-Search/API",
            "IMAGE",
        ),
        (
            "pimeyes",
            "DISABLED",
            "Facial identification is not supported by this project.",
            "https://pimeyes.com/en/faq",
            "IMAGE",
        ),
        (
            "surfface",
            "DISABLED",
            "Facial identification is not supported by this project.",
            "https://surfface.com/",
            "IMAGE",
        ),
    ]
    return tuple(
        RestrictedConnector(*spec) for spec in specs if spec[0] not in {"ghunt", "osintgram"}
    )
