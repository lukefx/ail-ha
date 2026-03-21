"""Ail Energy consumption"""

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.ail.api_client import AILEnergyClient
from custom_components.ail.const import (
    DOMAIN,
    CONF_SESSION_STATE,
    CONF_FIXED_TARIFF,
    CONF_PEAK_PRICE,
    CONF_OFF_PEAK_PRICE,
    LEGACY_CONF_FIXED_TARIFF,
    LEGACY_CONF_PEAK_PRICE,
    LEGACY_CONF_OFF_PEAK_PRICE,
    DAILY_PRICE_CHF,
    NIGHTLY_PRICE_CHF,
)
from custom_components.ail.coordinator import EnergyDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class RuntimeData:
    coordinator: DataUpdateCoordinator


PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML (legacy)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    _migrate_tariff_options(hass, entry)

    # Create coordinator
    client = AILEnergyClient(
        entry.data["username"],
        entry.data["password"],
        session_state=entry.data.get(CONF_SESSION_STATE),
    )
    data_coordinator = EnergyDataUpdateCoordinator(hass, entry, client)

    # Run coordinator setup (historical fetch when needed)
    await data_coordinator.async_setup()

    # Get initial data
    await data_coordinator.async_config_entry_first_refresh()

    # Store coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = data_coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.api_client.close()
    return unload_ok


def _migrate_tariff_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ensure tariff settings are stored in entry options."""
    options = dict(entry.options)
    data = entry.data

    def _get_value(key: str, legacy_key: str, default: Any) -> Any:
        if key in options:
            return options[key]
        if key in data:
            return data[key]
        if legacy_key in options:
            return options[legacy_key]
        if legacy_key in data:
            return data[legacy_key]
        return default

    legacy_option_keys = {
        LEGACY_CONF_FIXED_TARIFF,
        LEGACY_CONF_PEAK_PRICE,
        LEGACY_CONF_OFF_PEAK_PRICE,
    }
    new_options = {k: v for k, v in options.items() if k not in legacy_option_keys}
    new_options[CONF_FIXED_TARIFF] = bool(
        _get_value(CONF_FIXED_TARIFF, LEGACY_CONF_FIXED_TARIFF, False)
    )
    new_options[CONF_PEAK_PRICE] = float(
        _get_value(CONF_PEAK_PRICE, LEGACY_CONF_PEAK_PRICE, DAILY_PRICE_CHF)
    )
    new_options[CONF_OFF_PEAK_PRICE] = float(
        _get_value(CONF_OFF_PEAK_PRICE, LEGACY_CONF_OFF_PEAK_PRICE, NIGHTLY_PRICE_CHF)
    )

    if new_options != options:
        hass.config_entries.async_update_entry(entry, options=new_options)
