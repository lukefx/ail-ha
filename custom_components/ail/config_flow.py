"""Configuration flow for My Integration."""

from __future__ import annotations

import aiohttp
import voluptuous as vol
from typing import Any
from collections.abc import Mapping

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from . import AILEnergyClient
from .api_client import AILClientError
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_MFA_CODE,
    CONF_SESSION_STATE,
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
        self._auth_client = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

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
            # A fresh login attempt should not keep any prior MFA session alive.
            await self._close_auth_client()
            self.auth_data = None
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
            except MFARequired:
                self.auth_data = {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                return await self.async_step_mfa()
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

    # ------------------------------------------------------------------
    # Reauthentication
    # ------------------------------------------------------------------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Recover an existing entry whose stored AIL session expired.

        Home Assistant starts this flow when the coordinator raises
        ConfigEntryAuthFailed. Recovery is attempted silently first: the stored
        cookies normally still yield a Keycloak session, and only a genuine SSO
        expiry needs the user.
        """
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        self._reauth_entry = entry
        # Keep credentials and tariff settings; only the session state is new.
        self.auth_data = dict(entry.data)
        await self._close_auth_client()
        return await self._async_reauth_try_silent()

    async def _async_reauth_try_silent(self) -> FlowResult:
        """Renew the session without user input, falling back to a form."""
        auth_data: dict[str, Any] = self.auth_data or {}
        self.auth_data = auth_data
        try:
            await self._test_credentials(auth_data)
        except MFARequired:
            # Keycloak wants an email code: ask for the code and nothing else.
            return await self.async_step_mfa()
        except InvalidAuth:
            # The stored password is no longer accepted.
            return await self.async_step_reauth_credentials()
        except CannotConnect:
            return await self.async_step_reauth_credentials(
                errors={"base": "cannot_connect"}
            )
        return await self._async_finish_reauth()

    async def async_step_reauth_credentials(
        self,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        """Ask for credentials when the stored ones are rejected."""
        errors = dict(errors or {})
        auth_data: dict[str, Any] = self.auth_data or {}
        self.auth_data = auth_data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=auth_data.get(CONF_USERNAME, "")
                ): selector.TextSelector(
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
            await self._close_auth_client()
            # Cookies belong to the previous identifier: never reuse them.
            auth_data.pop(CONF_SESSION_STATE, None)
            auth_data.update(user_input)
            try:
                await self._test_credentials(auth_data)
            except MFARequired:
                return await self.async_step_mfa()
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                errors["base"] = "unknown"
            else:
                return await self._async_finish_reauth()

        return self.async_show_form(
            step_id="reauth_credentials",
            data_schema=schema,
            errors=errors,
        )

    async def _async_finish_reauth(self) -> FlowResult:
        """Persist the renewed session state and reload the entry."""
        entry = self._reauth_entry
        if entry is None:  # pragma: no cover - guarded by async_step_reauth
            return self.async_abort(reason="entry_not_found")

        auth_data: dict[str, Any] = self.auth_data or {}
        if not self._session_serves_entry(entry, auth_data):
            # Entities and long-term statistics are bound to the meter this
            # entry was created with: another account must not take it over.
            await self._close_auth_client()
            auth_data.pop(CONF_SESSION_STATE, None)
            return await self.async_step_reauth_credentials(
                errors={"base": "wrong_account"}
            )

        data = {
            **entry.data,
            CONF_USERNAME: auth_data[CONF_USERNAME],
            CONF_PASSWORD: auth_data[CONF_PASSWORD],
            CONF_SESSION_STATE: auth_data[CONF_SESSION_STATE],
        }
        await self._close_auth_client()
        self._reauth_entry = None
        return self.async_update_reload_and_abort(
            entry,
            data=data,
            reason="reauth_successful",
        )

    @staticmethod
    def _session_serves_entry(
        entry: config_entries.ConfigEntry, auth_data: dict[str, Any]
    ) -> bool:
        """Return False when the renewed session belongs to another meter."""
        stored = (entry.data.get(CONF_SESSION_STATE) or {}).get("meter_id")
        refreshed = (auth_data.get(CONF_SESSION_STATE) or {}).get("meter_id")
        if not stored or not refreshed:
            # Nothing to compare against (legacy entry, unscraped page).
            return True
        return str(stored) == str(refreshed)

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the second authentication factor step."""
        errors = {}
        schema = vol.Schema(
            {
                vol.Required(CONF_MFA_CODE): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                    ),
                )
            }
        )

        if user_input is not None:
            try:
                # If there is no active MFA session, treat this as an expired
                # or missing MFA state rather than an invalid MFA code.
                if not self._auth_client or not self._auth_client.is_mfa_pending():
                    # The Keycloak form is short lived. Restart the login so the
                    # user gets a fresh code instead of posting into a dead one.
                    await self._close_auth_client()
                    if self._reauth_entry is not None:
                        return await self._async_reauth_try_silent()
                    # Clear any stale authentication state so the user can
                    # restart the authentication flow cleanly.
                    self.auth_data = None
                    errors["base"] = "mfa_session_expired"
                else:
                    if not await self._auth_client.submit_mfa_code(
                        user_input[CONF_MFA_CODE]
                    ):
                        # A challenge that vanished server-side is an expiry,
                        # not a wrong code: restart instead of asking again.
                        if not self._auth_client.is_mfa_pending():
                            raise MfaSessionExpired()
                        # This specifically indicates a bad MFA code.
                        raise InvalidAuth()

                    self.auth_data[CONF_SESSION_STATE] = (
                        self._auth_client.export_session_state()
                    )
                    await self._close_auth_client()
                    if self._reauth_entry is not None:
                        return await self._async_finish_reauth()
                    return await self.async_step_tariff()
            except MfaSessionExpired:
                await self._close_auth_client()
                if self._reauth_entry is not None:
                    return await self._async_reauth_try_silent()
                # Adding an entry: re-ask Keycloak for a fresh challenge.
                try:
                    await self._test_credentials(self.auth_data)
                except MFARequired:
                    return await self.async_step_mfa()
                except (InvalidAuth, CannotConnect):
                    self.auth_data = None
                    return await self.async_step_user()
                else:
                    return await self.async_step_tariff()
            except InvalidAuth:
                errors["base"] = "invalid_mfa_code"
            except Exception:  # pylint: disable=broad-except
                await self._close_auth_client()
                if self._reauth_entry is None:
                    self.auth_data = None
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="mfa",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_tariff(
        self, user_input: dict[str, Any] | None = None
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
        client = AILEnergyClient(
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
            session_state=user_input.get(CONF_SESSION_STATE),
        )
        try:
            try:
                authenticated = await client.login()
            except (
                AILClientError,
                aiohttp.ClientError,
                TimeoutError,
                UnicodeError,
            ) as err:
                raise CannotConnect from err

            if not authenticated:
                if client.is_mfa_pending():
                    self._auth_client = client
                    raise MFARequired()
                raise InvalidAuth()
            user_input[CONF_SESSION_STATE] = client.export_session_state()
        finally:
            if client is not self._auth_client:
                await client.close()

    async def _close_auth_client(self) -> None:
        """Close and clear the in-flight auth client."""
        if self._auth_client:
            await self._auth_client.close()
            self._auth_client = None


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class MFARequired(HomeAssistantError):
    """Error to indicate MFA is required to complete login."""


class MfaSessionExpired(HomeAssistantError):
    """Error to indicate the pending MFA challenge is gone server-side."""
