"""Tests for the AIL API client."""

from unittest.mock import MagicMock

from custom_components.ail.api_client import AILEnergyClient


def test_extract_token_from_page_script():
    """Extract the EnergyBuddy app token from page HTML."""
    html = '<script>aWattgarde.config.token = "abc123";</script>'

    assert AILEnergyClient._extract_token(html) == "abc123"


def test_extract_meter_id_from_selected_meter():
    """Extract the selected meter from the page bootstrap data."""
    html = '<script>aWattgarde.Page.SelectedMeterID = 987654;</script>'

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
    cookie.__getitem__.side_effect = {"domain": ".account.ail.ch", "path": "/"}.get
    client.session.cookie_jar = [cookie]

    session_state = client.export_session_state()

    assert session_state == {
        "token": "token-1",
        "meter_id": "12345",
        "cookies": [
            {
                "name": "AUTH_SESSION_ID",
                "value": "cookie-value",
                "domain": ".account.ail.ch",
                "path": "/",
            }
        ],
    }
