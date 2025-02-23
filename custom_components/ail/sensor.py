import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType, StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.ail import EnergyDataUpdateCoordinator, DOMAIN
from custom_components.ail.coordinator import ConsumptionData

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class EnergyEntityDescription(SensorEntityDescription):
    value_fn: Callable[[ConsumptionData], str | float]


SENSORS: tuple[EnergyEntityDescription, ...] = (
    EnergyEntityDescription(
        key="day",
        name="Day: Last hour consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: data.day,
    ),
    EnergyEntityDescription(
        key="night",
        name="Night: last hour consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: data.night,
    ),
    EnergyEntityDescription(
        key="current",
        name="Last hour consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: data.total,
    ),
)


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
    async_add_entities(EnergySensor(coordinator, sensor) for sensor in SENSORS)


class EnergySensor(CoordinatorEntity[EnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(
        self, coordinator: EnergyDataUpdateCoordinator, sensor: EnergyEntityDescription
    ):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.sensor = sensor
        self._attr_unique_id = f"{DOMAIN}_energy_{sensor.key}"
        self._attr_name = sensor.name
        self._attr_state_class = self.sensor.state_class
        self._attr_device_class = self.sensor.device_class
        self._attr_suggested_display_precision = self.sensor.suggested_display_precision
        self._attr_native_unit_of_measurement = self.sensor.native_unit_of_measurement

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        _LOGGER.debug(f"Update sensor {self._attr_unique_id}")
        if not self.coordinator.data:
            return None
        return self.sensor.value_fn(self.coordinator.data)

    @property
    def last_reset(self) -> datetime | None:
        """Return the time when the sensor was last reset, if any."""
        if (
            not self.coordinator.data
            or self._attr_device_class is not SensorStateClass.TOTAL_INCREASING
        ):
            return None
        return self.coordinator.data.from_date
