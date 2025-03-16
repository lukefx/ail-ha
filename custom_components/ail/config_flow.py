"""Configuration flow for My Integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from . import AILEnergyClient
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_FIXED_TARIFF,
    CONF_PEAK_PRICE,
    CONF_OFF_PEAK_PRICE,
    DAILY_PRICE_CHF,
    NIGHTLY_PRICE_CHF,
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for My Integration."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.auth_data = None

    async def async_step_user(
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        # Define schema with descriptions
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                    ),
                ),
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD,
                    ),
                ),
            }
        )

        if user_input is not None:
            try:
                # Validate the credentials here if possible
                await self._test_credentials(user_input)

                # Store credentials and move to tariff step
                self.auth_data = user_input
                return await self.async_step_tariff()

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            description_placeholders={
                "login_url": "https://energybuddy.ail.ch",
                "account_create_url": "https://energybuddy.ail.ch/it/activation/",
            },
            errors=errors,
        )

    async def async_step_tariff(
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Handle the tariff configuration step."""
        errors = {}

        if user_input is not None:
            # Validate float values
            try:
                if not user_input[CONF_FIXED_TARIFF]:
                    float(user_input[CONF_PEAK_PRICE])
                    float(user_input[CONF_OFF_PEAK_PRICE])
                # Merge auth data with tariff data
                full_data = {**self.auth_data, **user_input}
                return self.async_create_entry(
                    title=self.auth_data[CONF_USERNAME],
                    data=full_data,
                )
            except ValueError:
                errors["base"] = "invalid_price"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_FIXED_TARIFF, default=False
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_PEAK_PRICE, default=DAILY_PRICE_CHF
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=20,
                        step=0.001,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
                vol.Required(
                    CONF_OFF_PEAK_PRICE, default=NIGHTLY_PRICE_CHF
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=20,
                        step=0.001,
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
            }
        )

        return self.async_show_form(
            step_id="tariff",
            data_schema=schema,
            errors=errors,
        )

    async def _test_credentials(self, user_input):
        """Test if we can authenticate with the credentials."""
        client = AILEnergyClient(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
        if not await client.login():
            raise InvalidAuth()


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
