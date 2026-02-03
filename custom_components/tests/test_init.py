"""Test component setup."""

from unittest.mock import AsyncMock, patch

from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ail.const import DOMAIN, ENERGY_CONSUMPTION_KEY

from custom_components.tests.conftest import auto_enable_custom_integrations  # noqa: F401


class _DummyRecorder:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


async def test_async_setup(hass):
    """Test the component gets setup."""
    assert await async_setup_component(hass, DOMAIN, {}) is True


async def test_async_setup_entry_fetches_history_when_no_stats(hass):
    """Ensure historical data fetch runs when no stats exist."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "user@example.com", "password": "secret"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.ail.api_client.AILEnergyClient.login", return_value=True
    ), patch(
        "custom_components.ail.coordinator.EnergyDataUpdateCoordinator._fetch_chunked_data",
        return_value={},
    ), patch(
        "custom_components.ail.coordinator.get_instance",
        return_value=_DummyRecorder(),
    ), patch(
        "custom_components.ail.coordinator.get_last_statistics",
        return_value={},
    ), patch(
        "custom_components.ail.coordinator.EnergyDataUpdateCoordinator._fetch_historical_data",
        new=AsyncMock(),
    ) as fetch_history:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        fetch_history.assert_awaited()


async def test_async_setup_entry_skips_history_when_stats_exist(hass):
    """Ensure historical fetch is skipped when stats exist."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "user@example.com", "password": "secret"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.ail.api_client.AILEnergyClient.login", return_value=True
    ), patch(
        "custom_components.ail.coordinator.EnergyDataUpdateCoordinator._fetch_chunked_data",
        return_value={},
    ), patch(
        "custom_components.ail.coordinator.get_instance",
        return_value=_DummyRecorder(),
    ), patch(
        "custom_components.ail.coordinator.get_last_statistics",
        return_value={ENERGY_CONSUMPTION_KEY: [{"start": 0, "sum": 0.0}]},
    ), patch(
        "custom_components.ail.coordinator.EnergyDataUpdateCoordinator._fetch_historical_data",
        new=AsyncMock(),
    ) as fetch_history:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        fetch_history.assert_not_awaited()
