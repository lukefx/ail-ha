import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_client import AILEnergyClient, ConsumptionResponse
from .const import (
    DOMAIN,
    ENERGY_CONSUMPTION_KEY,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class ConsumptionData:
    """Class for holding consumption data."""

    day: float
    night: float
    from_date: datetime
    to_date: datetime

    def get(self, property_name: str) -> any:
        """Get property value by name."""
        return getattr(self, property_name)

    @classmethod
    def from_api_response(cls, data: ConsumptionResponse) -> list["ConsumptionData"]:
        statistics = []
        for record in data.response:
            # Skip records with no readings
            if record.readings_count is not None:
                statistics.append(
                    cls(
                        day=record.day,
                        night=record.night,
                        from_date=record.from_,
                        to_date=record.to,
                    )
                )
        return statistics


class EnergyDataUpdateCoordinator(DataUpdateCoordinator[ConsumptionData]):
    """Class to manage fetching data from the API and updating statistics."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: AILEnergyClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # Ping the api every hour, so we provide the data as sensor and we try to add statistic
            update_interval=timedelta(hours=1),
        )
        self.api_client = client

    async def _async_update_data(self) -> ConsumptionData:
        """Update data via API and update statistics."""
        if not await self.api_client.login():
            raise ConfigEntryAuthFailed

        try:
            _from = datetime.now() - timedelta(days=5)
            _to = datetime.now()
            response = await self.api_client.get_consumption_data(_from, _to)
            consumption_data = ConsumptionData.from_api_response(response)
            _LOGGER.debug("Updated consumption data: %s", consumption_data)

            # Process hourly consumptions
            hourly_data = self._sum_hourly_consumptions(consumption_data)

            # Update statistics after getting new data
            await self._insert_statistics(hourly_data)
            return consumption_data[-1]
        except Exception as err:
            _LOGGER.error("Error fetching consumption data: %s", err)
            raise UpdateFailed(f"Error updating data: {err}") from err

    def _sum_hourly_consumptions(
        self, consumptions: list[ConsumptionData]
    ) -> dict[datetime, ConsumptionData]:
        hourly_sums = {}

        # Find the first entry that starts at the beginning of an hour
        start_idx = 0
        for idx, consumption in enumerate(consumptions):
            if consumption.from_date.minute == 0:
                start_idx = idx
                break

        # Process only from the first full hour
        for consumption in consumptions[start_idx:]:
            hour_key = consumption.from_date.replace(minute=0, second=0, microsecond=0)
            if hour_key not in hourly_sums:
                hourly_sums[hour_key] = ConsumptionData(
                    day=0.0,
                    night=0.0,
                    from_date=hour_key,
                    to_date=hour_key + timedelta(hours=1),
                )

            current = hourly_sums[hour_key]
            current.day += consumption.day

        return hourly_sums

    async def _insert_statistics(
        self, consumptions: dict[datetime, ConsumptionData]
    ) -> None:
        if not consumptions:
            _LOGGER.debug("No consumption data to process")
            return

        # Get last statistics time in a single query
        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, ENERGY_CONSUMPTION_KEY, True, {"sum"}
        )

        last_stats_time = (
            last_stat[ENERGY_CONSUMPTION_KEY][0]["start"] if last_stat else None
        )

        base_metadata = {
            "has_mean": False,
            "has_sum": True,
            "source": DOMAIN,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        }

        sums = last_stat[ENERGY_CONSUMPTION_KEY][0]["sum"] if last_stat else 0.0
        statistics = []

        # Prepare statistics for each hour
        for hour, consumption in consumptions.items():
            # Skip hours that are already processed
            if last_stats_time and hour.timestamp() <= last_stats_time:
                continue

            sums += consumption.day
            statistics.append(
                StatisticData(
                    start=hour,
                    state=consumption.day,
                    sum=sums,
                )
            )

        metadata = StatisticMetaData(
            statistic_id=ENERGY_CONSUMPTION_KEY,
            name="Energy consumption",
            **base_metadata,
        )

        async_add_external_statistics(self.hass, metadata, statistics)
