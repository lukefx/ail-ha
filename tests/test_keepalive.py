"""Tests for the Keycloak SSO keepalive."""

from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import Mock

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ail.api_client import AILClientError, AILEnergyClient
from custom_components.ail.const import DOMAIN, SSO_KEEPALIVE_INTERVAL
from custom_components.ail.coordinator import EnergyDataUpdateCoordinator

AUTHORIZE_URL = (
    "https://account.ail.ch/auth/realms/ail/protocol/openid-connect/auth"
    "?state=abc123&scope=email&response_type=code&approval_prompt=auto"
    "&redirect_uri=https%3A%2F%2Fenergybuddy.ail.ch%2Foauth2%2Flogin"
    "&client_id=energybuddy"
)
REDIRECT_URI = "https://energybuddy.ail.ch/oauth2/login"


class FakeResponse:
    """Minimal aiohttp response stand-in."""

    def __init__(self, location: str) -> None:
        self.headers = {"Location": location}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    """Records the probe request instead of leaving the host."""

    def __init__(self, location: str) -> None:
        self.location = location
        self.requests: list[tuple[str, bool]] = []

    def get(self, url: str, allow_redirects: bool = True) -> FakeResponse:
        self.requests.append((url, allow_redirects))
        return FakeResponse(self.location)


class FakeKeepaliveClient:
    """Answers keepalive calls from a fixed list."""

    def __init__(self, answers: list[bool | None]) -> None:
        self.answers = answers
        self.calls = 0

    async def keepalive(self) -> bool | None:
        self.calls += 1
        return self.answers.pop(0)


def _client_with(session: FakeSession) -> AILEnergyClient:
    client = AILEnergyClient("sito@example.com", "hunter2")
    client.token = "token"
    client._meter_id = "42"
    client.session = session
    client._authorize_url = AUTHORIZE_URL
    return client


def _coordinator(hass, client) -> EnergyDataUpdateCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, title="SitoCH", data={})
    entry.add_to_hass(hass)
    coordinator = EnergyDataUpdateCoordinator(hass, entry, client)
    coordinator._persist_session_state = Mock()
    return coordinator


def test_keepalive_interval_is_below_an_hour():
    """The keepalive must be frequent enough to matter."""
    assert SSO_KEEPALIVE_INTERVAL <= timedelta(minutes=30)


async def test_keepalive_reports_a_live_session():
    """A code-based redirect means the identity-provider session is alive."""
    session = FakeSession(f"{REDIRECT_URI}?code=xyz&state=abc123")
    client = _client_with(session)

    assert await client.keepalive() is True
    probe_url, allow_redirects = session.requests[0]
    assert "prompt=none" in probe_url
    assert "client_id=energybuddy" in probe_url
    assert allow_redirects is False


async def test_keepalive_detects_an_expired_session():
    """login_required is the explicit signal that the session is gone."""
    session = FakeSession(f"{REDIRECT_URI}?error=login_required&state=abc123")
    client = _client_with(session)

    assert await client.keepalive() is False


async def test_keepalive_without_a_session_does_nothing():
    """Before any successful login there is nothing to keep warm."""
    client = AILEnergyClient("sito@example.com", "hunter2")

    assert await client.keepalive() is None


async def test_coordinator_logs_the_session_loss_once(hass, caplog):
    """A dead session is reported on the transition, not every 30 minutes."""
    client = FakeKeepaliveClient([True, True, False, False, False])
    coordinator = _coordinator(hass, client)

    with caplog.at_level(logging.DEBUG, logger="custom_components.ail"):
        for _ in range(5):
            await coordinator.async_keepalive(dt_util.utcnow())

    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING
        and "identity-provider session" in record.message
    ]
    assert len(warnings) == 1
    # A live session persists what Keycloak handed back, so a restart resumes it.
    assert coordinator._persist_session_state.call_count == 2


async def test_coordinator_ignores_a_missing_session(hass, caplog):
    """No session yet is not an error and must not warn."""
    coordinator = _coordinator(hass, FakeKeepaliveClient([None, None]))

    with caplog.at_level(logging.DEBUG, logger="custom_components.ail"):
        await coordinator.async_keepalive(dt_util.utcnow())
        await coordinator.async_keepalive(dt_util.utcnow())

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    coordinator._persist_session_state.assert_not_called()


class FailingClient:
    """Always fails the keepalive request."""

    def __init__(self) -> None:
        self.calls = 0

    async def keepalive(self) -> bool:
        self.calls += 1
        raise AILClientError("AIL SSO keepalive request failed")


async def test_coordinator_warns_once_on_transport_failure(hass, caplog):
    """A broken keepalive is reported once, not every interval."""
    coordinator = _coordinator(hass, FailingClient())

    with caplog.at_level(logging.DEBUG, logger="custom_components.ail"):
        await coordinator.async_keepalive(dt_util.utcnow())
        await coordinator.async_keepalive(dt_util.utcnow())
        await coordinator.async_keepalive(dt_util.utcnow())

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "keepalive failed" in warnings[0].message
