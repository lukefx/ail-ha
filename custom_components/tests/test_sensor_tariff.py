"""Tests for tariff-aware sensors."""

from datetime import datetime, timedelta

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.util import dt as dt_util

from custom_components.ail.api_client import AILEnergyClient
from custom_components.ail.const import (
    CONF_FIXED_TARIFF,
    CONF_OFF_PEAK_PRICE,
    CONF_PEAK_PRICE,
    DOMAIN,
)
from custom_components.ail.coordinator import ConsumptionData, EnergyDataUpdateCoordinator
from custom_components.ail.sensor import EnergySensor, SENSORS


def _make_coordinator(hass, options):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "user@example.com", "password": "secret"},
        options=options,
    )
    entry.add_to_hass(hass)
    return EnergyDataUpdateCoordinator(hass, entry, AILEnergyClient("u", "p"))


def _get_cost_description():
    for description in SENSORS:
        if description.key == "cost":
            return description
    raise AssertionError("Cost sensor description not found")


def test_cost_sensor_uses_fixed_tariff(hass):
    """Fixed tariff should always return peak price."""
    tz = dt_util.get_time_zone("Europe/Zurich")
    dt_util.set_default_time_zone(tz)
    try:
        coordinator = _make_coordinator(
            hass,
            {
                CONF_FIXED_TARIFF: True,
                CONF_PEAK_PRICE: 0.3,
                CONF_OFF_PEAK_PRICE: 0.1,
            },
        )
        data = ConsumptionData(
            from_date=datetime(2024, 1, 1, 23, 0, 0),
            to_date=datetime(2024, 1, 2, 0, 0, 0),
            day=1.0,
        )
        coordinator.data = data
        sensor = EnergySensor(coordinator, _get_cost_description())
        assert sensor.native_value == 0.3
    finally:
        dt_util.set_default_time_zone(dt_util.UTC)


def test_cost_sensor_uses_day_night_rates(hass):
    """Dynamic tariff should pick off-peak or peak based on local hour."""
    tz = dt_util.get_time_zone("Europe/Zurich")
    dt_util.set_default_time_zone(tz)
    try:
        coordinator = _make_coordinator(
            hass,
            {
                CONF_FIXED_TARIFF: False,
                CONF_PEAK_PRICE: 0.3,
                CONF_OFF_PEAK_PRICE: 0.1,
            },
        )

        night_data = ConsumptionData(
            from_date=datetime(2024, 1, 1, 23, 30, 0),
            to_date=datetime(2024, 1, 2, 0, 30, 0),
            day=1.0,
        )
        coordinator.data = night_data
        sensor = EnergySensor(coordinator, _get_cost_description())
        assert sensor.native_value == 0.1

        day_data = ConsumptionData(
            from_date=datetime(2024, 1, 2, 12, 0, 0),
            to_date=datetime(2024, 1, 2, 13, 0, 0),
            day=1.0,
        )
        coordinator.data = day_data
        assert sensor.native_value == 0.3
    finally:
        dt_util.set_default_time_zone(dt_util.UTC)
