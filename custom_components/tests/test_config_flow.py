"""Tests for config flow."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.ail.config_flow import ConfigFlow, InvalidAuth, MFARequired
from custom_components.ail.const import (
    CONF_PASSWORD,
    CONF_SESSION_STATE,
    CONF_USERNAME,
    DOMAIN,
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
