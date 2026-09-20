"""Test component setup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.setup import async_setup_component
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ail.api_client import AILClientError
from custom_components.ail.const import DOMAIN, ENERGY_CONSUMPTION_KEY
from custom_components.ail.coordinator import EnergyDataUpdateCoordinator

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


async def test_async_unload_entry_closes_client(hass):
    """Ensure unloading an entry closes the API client session."""
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
        "custom_components.ail.api_client.AILEnergyClient.close",
        new=AsyncMock(),
    ) as close_client:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        close_client.assert_awaited()


async def test_transient_login_failure_does_not_request_reauthentication(hass):
    """Provider and transport failures should retry without invalidating auth."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "user@example.com", "password": "secret"},
    )
    client = SimpleNamespace(
        login=AsyncMock(side_effect=AILClientError("unexpected provider response"))
    )
    coordinator = EnergyDataUpdateCoordinator(hass, entry, client)

    with pytest.raises(UpdateFailed, match="Unable to authenticate with AIL"):
        await coordinator._async_update_data()


async def test_interactive_login_failure_requests_reauthentication(hass):
    """An explicit unsuccessful login should retain the reauthentication path."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "user@example.com", "password": "secret"},
    )
    client = SimpleNamespace(login=AsyncMock(return_value=False))
    coordinator = EnergyDataUpdateCoordinator(hass, entry, client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
