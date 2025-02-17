"""DataUpdateCoordinator for Daily Energy integration."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api_client import AILEnergyClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class ConsumptionData:
    """Class for holding consumption data."""

    day: float
    night: float
    total: float
    from_date: datetime
    to_date: datetime
    is_pending: bool
    readings_count: int

    def get(self, property_name: str) -> any:
        """Get property value by name."""
        return getattr(self, property_name)

    @classmethod
    def from_api_response(cls, data: dict) -> "ConsumptionData":
        """Create instance from API response."""
        if not data.get("response") or len(data["response"]) != 1:
            raise ValueError("API response must contain exactly one consumption record")
        response = data["response"][0]
        return cls(
            day=response["day"],
            night=response["night"],
            from_date=datetime.fromisoformat(response["from"]),
            to_date=datetime.fromisoformat(response["to"]),
            is_pending=response["isPending"],
            readings_count=response["readingsCount"],
            total=round(response["day"] + response["night"], 2),
        )


class EnergyDataUpdateCoordinator(DataUpdateCoordinator[ConsumptionData]):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, client: AILEnergyClient):
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=24),
        )
        self.api_client = client
        _LOGGER.debug(f"Coordinator initialised")

    async def _async_update_data(self) -> ConsumptionData:
        """Update data via API."""
        if await self.api_client.login():
            try:
                yesterday = date.today() - timedelta(days=1)
                raw_data = await self.api_client.get_consumption_data(yesterday)
                consumption = ConsumptionData.from_api_response(raw_data)
                _LOGGER.debug(f"async update with: {consumption}")
                return consumption
            except Exception as e:
                _LOGGER.error(f"Error fetching consumption data: {e}")
                raise
        raise ConfigEntryAuthFailed
