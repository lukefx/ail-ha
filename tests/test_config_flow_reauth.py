"""Tests for the AIL reauthentication config flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ail.const import (
    CONF_PASSWORD,
    CONF_SESSION_STATE,
    CONF_USERNAME,
    DOMAIN,
)

ENTRY_DATA: dict[str, Any] = {
    CONF_USERNAME: "sito@example.com",
    CONF_PASSWORD: "hunter2",
    CONF_SESSION_STATE: {"cookies": [], "token": "stale", "meter_id": "42"},
    "fixed_tariff": False,
    "peak_price": 0.258,
    "off_peak_price": 0.2347,
}

FRESH_SESSION = {"cookies": [], "token": "fresh", "meter_id": "42"}

PATCH_CLIENT = "custom_components.ail.config_flow.AILEnergyClient"


class FakeClient:
    """Minimal stand-in for AILEnergyClient."""

    def __init__(
        self,
        *,
        authenticated: bool = True,
        mfa_pending: bool = False,
        session_state: dict[str, Any] | None = None,
        fail: Exception | None = None,
        init_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.authenticated = authenticated
        self.mfa_pending = mfa_pending
        self.session_state = session_state or FRESH_SESSION
        self.fail = fail
        self.init_kwargs = init_kwargs
        self.closed = False
        self.login_calls = 0

    async def login(self) -> bool:
        self.login_calls += 1
        if self.fail is not None:
            raise self.fail
        return self.authenticated

    def is_mfa_pending(self) -> bool:
        return self.mfa_pending

    async def submit_mfa_code(self, code: str) -> bool:
        return code == "123456"

    def export_session_state(self) -> dict[str, Any]:
        return self.session_state

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Load the custom component inside the test instance."""
    yield


@pytest.fixture(autouse=True)
def _stub_reload(hass):
    """Keep the post-reauth entry reload out of the test.

    A real reload would set the integration up against the live service, so the
    reload is stubbed and its invocation is what the tests assert instead.
    """
    with patch.object(
        hass.config_entries, "async_reload", AsyncMock(return_value=True)
    ) as reload_mock:
        yield reload_mock


async def _add_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="SitoCH", data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)
    return entry


def _start_reauth(hass, entry):
    return hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )


async def test_reauth_recovers_silently(hass, _stub_reload):
    """A live SSO session renews the entry with no user interaction."""
    entry = await _add_entry(hass)
    client = FakeClient()

    with patch(PATCH_CLIENT, return_value=client) as client_cls:
        result = await _start_reauth(hass, entry)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    # Stored cookies must be offered to the client so silent SSO can work.
    assert (
        client_cls.call_args.kwargs["session_state"] == ENTRY_DATA[CONF_SESSION_STATE]
    )
    assert entry.data[CONF_SESSION_STATE] == FRESH_SESSION
    # The entry is updated in place: no duplicate entry, credentials untouched.
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert entry.data[CONF_PASSWORD] == ENTRY_DATA[CONF_PASSWORD]
    # The entry is reloaded so the coordinator resumes with the new session.
    _stub_reload.assert_awaited_once_with(entry.entry_id)


async def test_reauth_asks_only_for_the_code(hass):
    """A dead SSO session asks for the e-mailed code, not the password."""
    entry = await _add_entry(hass)
    client = FakeClient(authenticated=False, mfa_pending=True)

    with patch(PATCH_CLIENT, return_value=client):
        result = await _start_reauth(hass, entry)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "mfa"
    assert list(result["data_schema"].schema) == ["mfa_code"]

    client.mfa_pending = True
    with patch(PATCH_CLIENT, return_value=client):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"mfa_code": "123456"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_SESSION_STATE] == FRESH_SESSION
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reauth_rejects_a_wrong_code(hass):
    """A rejected code keeps the flow open and does not touch the entry."""
    entry = await _add_entry(hass)
    client = FakeClient(authenticated=False, mfa_pending=True)

    with patch(PATCH_CLIENT, return_value=client):
        result = await _start_reauth(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"mfa_code": "000000"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "mfa"
    assert result["errors"] == {"base": "invalid_mfa_code"}
    assert entry.data[CONF_SESSION_STATE] == ENTRY_DATA[CONF_SESSION_STATE]


async def test_reauth_falls_back_to_credentials(hass):
    """A rejected stored password asks for credentials, then finishes."""
    entry = await _add_entry(hass)
    rejected = FakeClient(authenticated=False, mfa_pending=False)
    accepted = FakeClient()

    with patch(PATCH_CLIENT, side_effect=[rejected, accepted]) as client_cls:
        result = await _start_reauth(hass, entry)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_credentials"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "new@example.com", CONF_PASSWORD: "newpass"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_USERNAME] == "new@example.com"
    assert entry.data[CONF_PASSWORD] == "newpass"
    # The stale session must not be replayed for a different identifier.
    assert client_cls.call_args.kwargs["session_state"] is None
    assert entry.data[CONF_SESSION_STATE] == FRESH_SESSION
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reauth_reports_transport_failure(hass):
    """A provider outage is surfaced instead of being treated as bad auth."""
    entry = await _add_entry(hass)
    client = FakeClient(fail=aiohttp.ClientError("boom"))

    with patch(PATCH_CLIENT, return_value=client):
        result = await _start_reauth(hass, entry)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_credentials"
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_SESSION_STATE] == ENTRY_DATA[CONF_SESSION_STATE]
