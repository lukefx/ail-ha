"""Tests for the AIL API client."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ail.api_client import (
    AILClientError,
    AILEnergyClient,
    parse_response,
    validate_ail_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://energybuddy.ail.ch/login",
        "https://evil.example/login",
        "https://energybuddy.ail.ch:8443/login",
        "https://user:password@energybuddy.ail.ch/login",
        "https://127.0.0.1/login",
        "//evil.example/login",
    ],
)
def test_rejects_unapproved_redirect_and_form_destinations(url):
    with pytest.raises(AILClientError):
        validate_ail_url(url, base="https://account.ail.ch/auth")


def test_accepts_only_exact_approved_hosts():
    assert (
        validate_ail_url("/auth", base="https://account.ail.ch/login")
        == "https://account.ail.ch/auth"
    )
    with pytest.raises(AILClientError):
        validate_ail_url("https://account.ail.ch.evil.example/auth")


def test_response_is_validated():
    raw = {
        "response": [
            {
                "from": "2026-01-01T00:00:00+00:00",
                "to": "2026-01-01T01:00:00+00:00",
                "day": 2,
                "night": 0,
                "isPending": False,
                "readingsCount": 4,
            },
        ]
    }
    result = parse_response(raw)
    assert result.response[0].from_ == datetime.fromisoformat(
        "2026-01-01T00:00:00+00:00"
    )


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_response_rejects_implausible_energy(value):
    with pytest.raises(AILClientError):
        parse_response(
            {
                "response": [
                    {
                        "from": "2026-01-01T00:00:00+00:00",
                        "to": "2026-01-01T01:00:00+00:00",
                        "day": value,
                        "isPending": False,
                        "readingsCount": 4,
                    }
                ]
            }
        )


def test_response_accepts_high_but_valid_consumption():
    result = parse_response(
        {
            "response": [
                {
                    "from": "2026-01-01T00:00:00+00:00",
                    "to": "2026-01-01T01:00:00+00:00",
                    "day": 250,
                    "isPending": False,
                    "readingsCount": 4,
                }
            ]
        }
    )
    assert result.response[0].day == 250


def test_extract_token_from_page_script():
    """Extract the EnergyBuddy app token from page HTML."""
    html = '<script>aWattgarde.config.token = "abc123";</script>'

    assert AILEnergyClient._extract_token(html) == "abc123"


def test_extract_meter_id_from_selected_meter():
    """Extract the selected meter from the page bootstrap data."""
    html = "<script>aWattgarde.Page.SelectedMeterID = 987654;</script>"

    assert AILEnergyClient._extract_meter_id(html) == "987654"


def test_extract_meter_id_from_json_fallback():
    """Fall back to meterID JSON if the page format changes."""
    html = '{"meterID":"12345"}'

    assert AILEnergyClient._extract_meter_id(html) == "12345"


def test_detect_pending_mfa_from_keycloak_form():
    """Detect the email-code MFA form returned by Keycloak."""
    client = AILEnergyClient("user@example.com", "secret")
    html = """
    <form id="kc-otp-login-form" action="/auth/realms/ail/login-actions/authenticate">
        <input type="hidden" name="credentialId" value="">
        <input type="hidden" name="tryAnotherWay" value="on">
        <input type="text" name="otp" autocomplete="one-time-code">
    </form>
    """

    assert client._update_pending_mfa(html, "https://account.ail.ch/auth/step")
    assert client.is_mfa_pending()
    assert client._pending_mfa_field == "otp"
    assert client._pending_mfa_action == (
        "https://account.ail.ch/auth/realms/ail/login-actions/authenticate"
    )


def test_export_session_state_includes_restorable_cookies():
    """Persist cookies together with token and meter id."""
    client = AILEnergyClient("user@example.com", "secret")
    client.token = "token-1"
    client._meter_id = "12345"
    client.session = MagicMock()
    cookie = MagicMock()
    cookie.key = "AUTH_SESSION_ID"
    cookie.value = "cookie-value"
    cookie.__getitem__.side_effect = {
        "domain": ".account.ail.ch",
        "path": "/",
        "secure": True,
        "httponly": True,
        "samesite": "Lax",
        "expires": "",
        "max-age": "",
    }.get
    client.session.cookie_jar = [cookie]

    session_state = client.export_session_state()

    assert session_state == {
        "token": "token-1",
        "meter_id": "12345",
        "cookies": [
            {
                "name": "AUTH_SESSION_ID",
                "value": "cookie-value",
                "domain": "account.ail.ch",
                "path": "/",
                "secure": True,
                "httponly": True,
                "samesite": "Lax",
                "expires": "",
                "max-age": "",
            }
        ],
    }


def test_export_drops_unapproved_domain_cookies():
    client = AILEnergyClient("user@example.com", "secret")
    client.session = MagicMock()
    cookie = MagicMock()
    cookie.key = "stolen"
    cookie.value = "secret"
    cookie.__getitem__.side_effect = {"domain": "evil.example"}.get
    client.session.cookie_jar = [cookie]
    assert client.export_session_state()["cookies"] == []


def test_build_keycloak_login_payload_enables_remember_me():
    """Send remember-me using the parameter name observed on the live form."""
    client = AILEnergyClient("user@example.com", "secret")

    payload = client._build_keycloak_login_payload()

    assert payload == {
        "username": "user@example.com",
        "password": "secret",
        "credentialId": "",
        "login": "ACCEDI",
        "rememberMe": "on",
    }


@pytest.mark.asyncio
async def test_login_accepts_remembered_keycloak_session():
    """A silent Keycloak SSO redirect should restore the EnergyBuddy session."""
    client = AILEnergyClient("user@example.com", "secret")
    client.session = MagicMock()
    client._request = AsyncMock(
        side_effect=[
            (client.LOGIN_URL, b""),
            (
                client.BASE_URL,
                (
                    b'<script>aWattgarde.config.token = "token-1";'
                    b"aWattgarde.Page.SelectedMeterID = 12345;</script>"
                ),
            ),
        ]
    )
    client._refresh_session_state = AsyncMock(return_value=False)
    client._start_oauth_login = AsyncMock(
        return_value="https://account.ail.ch/auth/realms/ail/protocol/openid-connect/auth"
    )
    client._submit_keycloak_credentials = AsyncMock()

    assert await client.login() is True
    assert client.token == "token-1"
    assert client.get_meter_id() == "12345"
    client._submit_keycloak_credentials.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_rejects_unrecognized_keycloak_response_as_provider_error():
    """An unexpected provider page is not proof that credentials are invalid."""
    client = AILEnergyClient("user@example.com", "secret")
    client.session = MagicMock()
    client._request = AsyncMock(
        side_effect=[
            (client.LOGIN_URL, b""),
            (
                "https://account.ail.ch/auth/realms/ail/unexpected",
                b"<html><body>Temporarily unavailable</body></html>",
            ),
        ]
    )
    client._refresh_session_state = AsyncMock(return_value=False)
    client._start_oauth_login = AsyncMock(
        return_value="https://account.ail.ch/auth/realms/ail/protocol/openid-connect/auth"
    )

    with pytest.raises(AILClientError, match="login form"):
        await client.login()
