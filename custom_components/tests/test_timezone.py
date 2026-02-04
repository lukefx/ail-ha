"""Tests for timezone handling."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.util import dt as dt_util

from custom_components.ail.api_client import AILEnergyClient
from custom_components.ail.const import DOMAIN
from custom_components.ail.coordinator import ConsumptionData, EnergyDataUpdateCoordinator


class _DummyRecorder:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _make_coordinator(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "user@example.com", "password": "secret"},
    )
    entry.add_to_hass(hass)
    return EnergyDataUpdateCoordinator(hass, entry, AILEnergyClient("u", "p"))


def test_sum_hourly_consumptions_uses_local_time(hass):
    """Naive datetimes should be treated as local for day/night bucketing."""
    tz = dt_util.get_time_zone("Europe/Zurich")
    dt_util.set_default_time_zone(tz)
    try:
        coordinator = _make_coordinator(hass)

        # 23:15 local should be night; 12:10 local should be day
        night_base = datetime(2024, 1, 1, 23, 15, 0)
        day_base = datetime(2024, 1, 2, 12, 10, 0)

        consumptions = []
        for _ in range(4):
            consumptions.append(
                ConsumptionData(
                    from_date=night_base,
                    to_date=night_base + timedelta(hours=1),
                    day=1.0,
                )
            )
            consumptions.append(
                ConsumptionData(
                    from_date=day_base,
                    to_date=day_base + timedelta(hours=1),
                    day=2.0,
                )
            )

        hourly = coordinator._sum_hourly_consumptions(consumptions)

        night_key = dt_util.as_local(night_base).replace(
            minute=0, second=0, microsecond=0
        )
        day_key = dt_util.as_local(day_base).replace(minute=0, second=0, microsecond=0)

        assert night_key in hourly
        assert day_key in hourly
        assert hourly[night_key].night == 4.0
        assert hourly[night_key].day == 0.0
        assert hourly[day_key].day == 8.0
        assert hourly[day_key].night == 0.0
    finally:
        dt_util.set_default_time_zone(dt_util.UTC)


@pytest.mark.asyncio
async def test_insert_statistics_uses_utc_start(hass):
    """Statistic start timestamps should be stored in UTC."""
    tz = dt_util.get_time_zone("Europe/Zurich")
    dt_util.set_default_time_zone(tz)
    try:
        coordinator = _make_coordinator(hass)
        local_hour = dt_util.now().replace(minute=0, second=0, microsecond=0)
        consumptions = {
            local_hour: ConsumptionData(
                from_date=local_hour,
                to_date=local_hour + timedelta(hours=1),
                day=1.0,
            )
        }
        captured = {}

        def _capture_stats(_hass, _metadata, statistics):
            captured["stats"] = statistics

        with patch(
            "custom_components.ail.coordinator.get_last_statistics", return_value={}
        ), patch(
            "custom_components.ail.coordinator.get_instance",
            return_value=_DummyRecorder(),
        ), patch(
            "custom_components.ail.coordinator.async_add_external_statistics",
            new=_capture_stats,
        ):
            await coordinator._insert_statistic_type(
                consumptions,
                "day",
                "test:stat",
                "Test stat",
                metadata={"unit_of_measurement": None},
            )

        assert "stats" in captured
        assert captured["stats"][0]["start"].tzinfo == dt_util.UTC
    finally:
        dt_util.set_default_time_zone(dt_util.UTC)
