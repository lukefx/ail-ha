import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

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
from homeassistant.util import dt as dt_util

from custom_components.ail import DOMAIN
from custom_components.ail.api_client import EstimatedConsumptionCategory
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
        if 6 <= dt_util.as_local(data.from_date).hour < 22
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

    # Create measured-consumption sensors from the static descriptions.
    entities = [EnergySensor(coordinator, description) for description in SENSORS]
    async_add_entities(entities)

    known_breakdown_entities: set[str] = set()

    def add_breakdown_entities() -> None:
        """Add new provider categories while preserving existing entity IDs."""
        breakdown = coordinator.estimated_breakdown
        if breakdown is None:
            return

        new_entities: list[SensorEntity] = []
        if "total" not in known_breakdown_entities:
            known_breakdown_entities.add("total")
            new_entities.append(EstimatedWeeklyTotalSensor(coordinator))

        for category in breakdown.categories:
            if category.stable_key in known_breakdown_entities:
                continue
            known_breakdown_entities.add(category.stable_key)
            new_entities.append(
                EstimatedWeeklyCategorySensor(
                    coordinator,
                    category.stable_key,
                    category.name,
                )
            )

        if new_entities:
            async_add_entities(new_entities)

    add_breakdown_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_breakdown_entities))


def _device_info(coordinator: EnergyDataUpdateCoordinator) -> dict[str, Any]:
    """Return common device metadata for AIL entities."""
    return {
        "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
        "name": "AIL Energy Consumption",
        "manufacturer": "AIL Lugano",
        "model": "Energy Buddy",
        "sw_version": "1.0",
    }


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
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        if self.entity_description.key == "cost":
            return self.coordinator.get_current_price(self.coordinator.data.from_date)
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def last_reset(self) -> Optional[datetime]:
        """Return the time when the sensor was last reset, if any."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.from_date


class EstimatedWeeklyTotalSensor(
    CoordinatorEntity[EnergyDataUpdateCoordinator], SensorEntity
):
    """Energy Buddy's modeled total weekly consumption."""

    _attr_has_entity_name = True
    _attr_name = "Estimated weekly consumption"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:chart-pie"

    def __init__(self, coordinator: EnergyDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{DOMAIN}_{coordinator.entry.entry_id}_estimated_weekly_total"
        )
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> StateType:
        breakdown = self.coordinator.estimated_breakdown
        return breakdown.total_consumption_kwh_per_week if breakdown else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"estimate_period": "week", "estimated": True}


class EstimatedWeeklyCategorySensor(
    CoordinatorEntity[EnergyDataUpdateCoordinator], SensorEntity
):
    """Energy Buddy's modeled weekly consumption for one category."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:chart-pie"

    def __init__(
        self,
        coordinator: EnergyDataUpdateCoordinator,
        category_key: str,
        category_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._category_key = category_key
        self._attr_name = f"Estimated weekly {category_name} consumption"
        self._attr_unique_id = (
            f"{DOMAIN}_{coordinator.entry.entry_id}_estimated_weekly_category_"
            f"{category_key}"
        )
        self._attr_device_info = _device_info(coordinator)

    @property
    def _category(self) -> EstimatedConsumptionCategory | None:
        breakdown = self.coordinator.estimated_breakdown
        if breakdown is None:
            return None
        return next(
            (
                category
                for category in breakdown.categories
                if category.stable_key == self._category_key
            ),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self._category is not None

    @property
    def native_value(self) -> StateType:
        category = self._category
        return category.consumption_kwh_per_week if category else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        category = self._category
        return {
            "estimate_period": "week",
            "estimated": True,
            "share_percent": category.share_percent if category else None,
        }
