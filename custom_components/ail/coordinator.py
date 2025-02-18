import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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
    """Class to manage fetching data from the API and updating statistics."""

    def __init__(self, hass: HomeAssistant, client: AILEnergyClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=24),
        )
        self.api_client = client
        self.hass = hass

        @callback
        def _dummy_listener() -> None:
            pass

        # Force periodic updates by registering at least one listener
        self.async_add_listener(_dummy_listener)

    async def _async_update_data(self) -> ConsumptionData:
        """Update data via API and update statistics."""
        if not await self.api_client.login():
            raise ConfigEntryAuthFailed

        try:
            yesterday = date.today() - timedelta(days=1)
            raw_data = await self.api_client.get_consumption_data(yesterday)
            consumption = ConsumptionData.from_api_response(raw_data)
            _LOGGER.debug("Updated consumption data: %s", consumption)

            # Update statistics after getting new data
            await self._insert_statistics(consumption)

            return consumption
        except Exception as err:
            _LOGGER.error("Error fetching consumption data: %s", err)
            raise UpdateFailed(f"Error updating data: {err}") from err

    async def _insert_statistics(self, consumption: ConsumptionData) -> None:
        """Insert energy consumption statistics."""
        # Define statistic IDs for different metrics
        day_statistic_id = f"{DOMAIN}:day_consumption"
        night_statistic_id = f"{DOMAIN}:night_consumption"
        total_statistic_id = f"{DOMAIN}:total_consumption"

        # Get the last statistics to determine the starting point
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            total_statistic_id,
            True,
            set(),
        )

        if not last_stats:
            _LOGGER.debug("Initializing statistics for the first time")
            day_sum = night_sum = total_sum = 0.0
        else:
            # Get existing sums from the last statistics
            stats = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                consumption.from_date,
                None,
                {day_statistic_id, night_statistic_id, total_statistic_id},
                "hour",
                None,
                {"sum"},
            )
            if not stats:
                day_sum = night_sum = total_sum = 0.0
            else:
                day_sum = stats[day_statistic_id][0]["sum"] if day_statistic_id in stats else 0.0
                night_sum = stats[night_statistic_id][0]["sum"] if night_statistic_id in stats else 0.0
                total_sum = stats[total_statistic_id][0]["sum"] if total_statistic_id in stats else 0.0

        # Update sums with new consumption data
        day_sum += consumption.day
        night_sum += consumption.night
        total_sum += consumption.total

        # Create statistics data
        start_time = consumption.from_date

        day_statistics = [
            StatisticData(
                start=start_time,
                state=consumption.day,
                sum=day_sum,
            )
        ]

        night_statistics = [
            StatisticData(
                start=start_time,
                state=consumption.night,
                sum=night_sum,
            )
        ]

        total_statistics = [
            StatisticData(
                start=start_time,
                state=consumption.total,
                sum=total_sum,
            )
        ]

        # Create metadata for each metric
        base_metadata = {
            "has_mean": False,
            "has_sum": True,
            "source": DOMAIN,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        }

        day_metadata = StatisticMetaData(
            statistic_id=day_statistic_id,
            name=f"{DOMAIN} Day Consumption",
            **base_metadata,
        )

        night_metadata = StatisticMetaData(
            statistic_id=night_statistic_id,
            name=f"{DOMAIN} Night Consumption",
            **base_metadata,
        )

        total_metadata = StatisticMetaData(
            statistic_id=total_statistic_id,
            name=f"{DOMAIN} Total Consumption",
            **base_metadata,
        )

        # Add statistics to the database
        _LOGGER.debug("Adding statistics for day consumption")
        async_add_external_statistics(self.hass, day_metadata, day_statistics)

        _LOGGER.debug("Adding statistics for night consumption")
        async_add_external_statistics(self.hass, night_metadata, night_statistics)

        _LOGGER.debug("Adding statistics for total consumption")
        async_add_external_statistics(self.hass, total_metadata, total_statistics)
