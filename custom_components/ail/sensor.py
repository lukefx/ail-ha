import logging
from datetime import datetime, timedelta
from typing import Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
    SensorEntity,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from custom_components.ail import EnergyDataUpdateCoordinator, DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=24)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the AIL sensor platform."""
    if discovery_info is None:
        return
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities(
        EnergySensor(coordinator, ent) for ent in ["day", "night", "total"]
    )


class EnergySensor(SensorEntity):
    """Representation of a Sensor."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, coordinator: EnergyDataUpdateCoordinator, ent: str):
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_energy_{ent}"
        self._attr_name = f"{ent} energy consumed"
        self.ent = ent

        # _attr_suggested_display_precision = 0
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY

    async def async_update(self):
        """Update the entity."""
        await self.coordinator.async_request_refresh()
        self._attr_extra_state_attributes = {
            "last_update": self.coordinator.data.to_date
        }

    @property
    def last_reset(self) -> Optional[datetime]:
        """Return the time when the sensor was last reset."""
        return self.coordinator.data.to_date

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self.ent)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success
