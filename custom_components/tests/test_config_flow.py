"""Tests for config flow."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.ail.config_flow import ConfigFlow, InvalidAuth
from custom_components.ail.const import CONF_PASSWORD, CONF_USERNAME, DOMAIN


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
