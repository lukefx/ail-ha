import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.ail import DOMAIN
from custom_components.ail.const import DAILY_PRICE_CHF, NIGHTLY_PRICE_CHF
from custom_components.ail.coordinator import (
    ConsumptionData,
    EnergyDataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class EnergyEntityDescription(SensorEntityDescription):
    """Description class for energy sensors."""

    value_fn: Callable[[ConsumptionData], StateType]


SENSORS: tuple[EnergyEntityDescription, ...] = (
    EnergyEntityDescription(
        key="day",
        name="Day consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        icon="mdi:weather-sunny",
        value_fn=lambda data: data.day if data else None,
    ),
    EnergyEntityDescription(
        key="night",
        name="Night consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        icon="mdi:weather-night",
        value_fn=lambda data: data.night if data else None,
    ),
    EnergyEntityDescription(
        key="total",
        name="Total consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        icon="mdi:chart-timeline-variant",
        value_fn=lambda data: (data.day + data.night) if data else None,
    ),
    EnergyEntityDescription(
        key="cost",
        name="Current price of the energy consumption",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="CHF",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
        value_fn=lambda data: DAILY_PRICE_CHF
        if 6 <= data.from_date.hour < 22
        else NIGHTLY_PRICE_CHF,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AIL energy sensors based on config entry."""
    coordinator: EnergyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create all sensors from the SENSORS description tuple
    entities = [EnergySensor(coordinator, description) for description in SENSORS]

    async_add_entities(entities)


class EnergySensor(CoordinatorEntity[EnergyDataUpdateCoordinator], SensorEntity):
    """Sensor for AIL energy consumption."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EnergyDataUpdateCoordinator,
        description: EnergyEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_energy_{description.key}"
        self._attr_name = description.name
        self._attr_state_class = description.state_class
        self._attr_device_class = description.device_class
        self._attr_suggested_display_precision = description.suggested_display_precision
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_icon = description.icon

        # Add device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "AIL Energy Consumption",
            "manufacturer": "AIL Lugano",
            "model": "Energy Buddy",
            "sw_version": "1.0",
            "via_device": None,
        }

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def last_reset(self) -> Optional[datetime]:
        """Return the time when the sensor was last reset, if any."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.from_date
