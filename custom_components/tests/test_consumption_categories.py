"""Tests for Energy Buddy estimated consumption categories."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.ail.api_client import parse_appliance_response
from custom_components.ail.coordinator import EnergyDataUpdateCoordinator
from custom_components.ail.sensor import (
    EstimatedWeeklyCategorySensor,
    EstimatedWeeklyTotalSensor,
)


def _breakdown(categories=None):
    categories = categories or [{"name": "Laundry", "consumptionInkWhPerWeek": 12.75}]
    category_map = {
        category["name"]: index + 10 for index, category in enumerate(categories)
    }
    response = parse_appliance_response(
        {
            "response": {
                "status": "success",
                "chartData": {
                    "totalConsumptionInkWhPerWeek": 42.5,
                    "categories": categories,
                },
                "data": {"applianceCategoriesMap": category_map},
            }
        }
    )
    return response.response.chart_data


def test_estimated_category_sensor_is_clearly_non_authoritative():
    coordinator = MagicMock()
    coordinator.entry.entry_id = "entry-1"
    coordinator.estimated_breakdown = _breakdown()

    sensor = EstimatedWeeklyCategorySensor(coordinator, "id-10", "Laundry")

    assert sensor.native_value == 12.75
    assert sensor.extra_state_attributes == {
        "estimate_period": "week",
        "estimated": True,
        "share_percent": 30.0,
    }
    assert sensor.unique_id == "ail_entry-1_estimated_weekly_category_id-10"


def test_estimated_category_sensor_reads_updated_coordinator_value():
    coordinator = MagicMock()
    coordinator.entry.entry_id = "entry-1"
    coordinator.estimated_breakdown = _breakdown()
    sensor = EstimatedWeeklyCategorySensor(coordinator, "id-10", "Laundry")

    coordinator.estimated_breakdown = _breakdown(
        [{"name": "Laundry", "consumptionInkWhPerWeek": 20.0}]
    )

    assert sensor.native_value == 20.0
    assert sensor.extra_state_attributes["share_percent"] == 47.06


def test_estimated_total_sensor_exposes_modeled_weekly_total():
    coordinator = MagicMock()
    coordinator.entry.entry_id = "entry-1"
    coordinator.estimated_breakdown = _breakdown()

    sensor = EstimatedWeeklyTotalSensor(coordinator)

    assert sensor.native_value == 42.5
    assert sensor.extra_state_attributes == {
        "estimate_period": "week",
        "estimated": True,
    }


async def test_breakdown_refresh_is_throttled_and_keeps_last_good_data(hass):
    entry = SimpleNamespace(entry_id="entry-1", data={}, options={})
    client = MagicMock()
    client.get_consumption_breakdown = AsyncMock(
        return_value=parse_appliance_response(
            {
                "response": {
                    "status": "success",
                    "chartData": {
                        "totalConsumptionInkWhPerWeek": 42.5,
                        "categories": [],
                    },
                    "data": {"applianceCategoriesMap": {}},
                }
            }
        )
    )
    coordinator = EnergyDataUpdateCoordinator(hass, entry, client)

    with patch(
        "custom_components.ail.coordinator.dt_util.utcnow",
        return_value=datetime(2026, 9, 19, tzinfo=timezone.utc),
    ):
        await coordinator._refresh_estimated_breakdown()
        await coordinator._refresh_estimated_breakdown()

    client.get_consumption_breakdown.assert_awaited_once()
    assert coordinator.estimated_breakdown.total_consumption_kwh_per_week == 42.5
