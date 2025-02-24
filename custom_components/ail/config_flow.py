"""Configuration flow for My Integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from . import AILEnergyClient
from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for My Integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        # Define schema with descriptions
        schema = vol.Schema({
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
        })

        if user_input is not None:
            try:
                # Validate the credentials here if possible
                await self._test_credentials(user_input)

                # If validation passes, create the config entry
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=user_input
                )
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

    async def _test_credentials(self, user_input):
        """Test if we can authenticate with the credentials."""
        client = AILEnergyClient(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
        with client:
            if not await client.login():
                raise InvalidAuth()


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
