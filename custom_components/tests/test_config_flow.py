"""Tests for config flow."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.ail.config_flow import ConfigFlow, InvalidAuth, MFARequired
from custom_components.ail.const import (
    CONF_MFA_CODE,
    CONF_PASSWORD,
    CONF_SESSION_STATE,
    CONF_USERNAME,
)


@pytest.mark.asyncio
async def test_test_credentials_closes_client_on_success(hass):
    """Ensure config flow closes the client after successful login."""
    flow = ConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.ail.config_flow.AILEnergyClient.login",
        new=AsyncMock(return_value=True),
    ), patch(
        "custom_components.ail.config_flow.AILEnergyClient.close",
        new=AsyncMock(),
    ) as close_client:
        await flow._test_credentials(
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
        )
        close_client.assert_awaited()


@pytest.mark.asyncio
async def test_test_credentials_closes_client_on_invalid_auth(hass):
    """Ensure config flow closes the client when auth fails."""
    flow = ConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.ail.config_flow.AILEnergyClient.login",
        new=AsyncMock(return_value=False),
    ), patch(
        "custom_components.ail.config_flow.AILEnergyClient.close",
        new=AsyncMock(),
    ) as close_client:
        with pytest.raises(InvalidAuth):
            await flow._test_credentials(
                {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "wrong"}
            )
        close_client.assert_awaited()


@pytest.mark.asyncio
async def test_test_credentials_stores_session_state(hass):
    """Successful auth should persist the reusable session state."""
    flow = ConfigFlow()
    flow.hass = hass
    user_input = {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}

    with patch(
        "custom_components.ail.config_flow.AILEnergyClient.login",
        new=AsyncMock(return_value=True),
    ), patch(
        "custom_components.ail.config_flow.AILEnergyClient.export_session_state",
        return_value={"token": "token", "meter_id": "1", "cookies": []},
    ), patch(
        "custom_components.ail.config_flow.AILEnergyClient.close",
        new=AsyncMock(),
    ):
        await flow._test_credentials(user_input)

    assert user_input[CONF_SESSION_STATE]["token"] == "token"


@pytest.mark.asyncio
async def test_test_credentials_raises_mfa_required_without_closing_pending_client(hass):
    """Preserve the in-progress auth client when MFA is required."""
    flow = ConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.ail.config_flow.AILEnergyClient.login",
        new=AsyncMock(return_value=False),
    ), patch(
        "custom_components.ail.config_flow.AILEnergyClient.is_mfa_pending",
        return_value=True,
    ), patch(
        "custom_components.ail.config_flow.AILEnergyClient.close",
        new=AsyncMock(),
    ) as close_client:
        with pytest.raises(MFARequired):
            await flow._test_credentials(
                {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
            )

    close_client.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_step_user_closes_stale_mfa_client_before_new_login(hass):
    """A new login attempt should close any previous pending MFA client."""
    flow = ConfigFlow()
    flow.hass = hass
    stale_client = SimpleNamespace(close=AsyncMock())
    flow._auth_client = stale_client
    flow.auth_data = {
        CONF_USERNAME: "old@example.com",
        CONF_PASSWORD: "old-secret",
    }

    with patch.object(flow, "_test_credentials", new=AsyncMock()) as test_credentials, patch.object(
        flow, "async_step_tariff", new=AsyncMock(return_value={"type": "form"})
    ) as async_step_tariff:
        result = await flow.async_step_user(
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
        )

    stale_client.close.assert_awaited_once()
    assert flow._auth_client is None
    test_credentials.assert_awaited_once()
    async_step_tariff.assert_awaited_once()
    assert flow.auth_data == {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "secret",
    }
    assert result == {"type": "form"}


@pytest.mark.asyncio
async def test_async_step_mfa_closes_client_when_session_is_expired(hass):
    """Expired MFA state should close and clear the pending auth client."""
    flow = ConfigFlow()
    flow.hass = hass
    flow.auth_data = {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "secret",
    }
    flow._auth_client = SimpleNamespace(
        is_mfa_pending=lambda: False,
        close=AsyncMock(),
    )

    result = await flow.async_step_mfa({CONF_MFA_CODE: "123456"})

    assert result["type"] == "form"
    assert result["step_id"] == "mfa"
    assert result["errors"] == {"base": "mfa_session_expired"}
    assert flow.auth_data is None
    assert flow._auth_client is None
