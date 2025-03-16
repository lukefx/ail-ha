"""Ail Energy consumption"""

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.ail.api_client import AILEnergyClient
from custom_components.ail.const import DOMAIN
from custom_components.ail.coordinator import EnergyDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

type AilConfigEntry = ConfigEntry[RuntimeData]


@dataclass
class RuntimeData:
    coordinator: DataUpdateCoordinator


PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    # Create coordinator
    client = AILEnergyClient(entry.data["username"], entry.data["password"])
    data_coordinator = EnergyDataUpdateCoordinator(hass, entry, client)

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
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
