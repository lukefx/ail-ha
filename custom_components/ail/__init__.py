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
from custom_components.ail.sensor import EnergySensor

_LOGGER = logging.getLogger(__name__)

type AilConfigEntry = ConfigEntry[RuntimeData]


@dataclass
class RuntimeData:
    coordinator: DataUpdateCoordinator


PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: AilConfigEntry) -> bool:
    """Set up the My Integration component."""
    if DOMAIN not in config:
        return True

    username = config[DOMAIN].get("username")
    password = config[DOMAIN].get("password")

    client = AILEnergyClient(username, password)
    data_coordinator = EnergyDataUpdateCoordinator(hass, client)

    await data_coordinator.async_refresh()
    # await data_coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN] = {
        "coordinator": data_coordinator,
    }

    for platform in PLATFORMS:
        hass.async_create_task(
            hass.helpers.discovery.async_load_platform(platform, DOMAIN, {}, config)
        )

    # Set up sensor platform
    # await async_setup_component(hass, "sensor", {"sensor": [{"platform": DOMAIN}]})
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
