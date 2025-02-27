import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from homeassistant.config_entries import ConfigEntry

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_client import AILEnergyClient, ConsumptionResponse
from .const import (
    DOMAIN,
    DAY_CONSUMPTION_KEY,
    NIGHT_CONSUMPTION_KEY,
    TOTAL_CONSUMPTION_KEY,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class ConsumptionData:
    """Class for holding consumption data."""

    day: float
    night: float
    total: float
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
                        total=record.day + record.night,
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
            _from = datetime.now() - timedelta(days=4)
            _to = datetime.now() - timedelta(days=1)
            response = await self.api_client.get_consumption_data(_from, _to)
            consumption_stats = ConsumptionData.from_api_response(response)

            # Handle empty consumption_stats array
            if not consumption_stats:
                _LOGGER.warning("No consumption data received from API")
                return ConsumptionData(
                    day=0.0,
                    night=0.0,
                    total=0.0,
                    from_date=_from,
                    to_date=_to
                )

            await self._insert_statistics(consumption_stats)
            _LOGGER.debug("Updated consumption data: %s", consumption_stats)
                            
            return consumption_stats[-1]
        except Exception as err:
            _LOGGER.error("Error fetching consumption data: %s", err)
            raise UpdateFailed(f"Error updating data: {err}") from err

    def _sum_hourly_consumptions(
        self, consumptions: list[ConsumptionData]
    ) -> dict[datetime, ConsumptionData]:
        """Sum consumption data by hour with O(n) complexity."""
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
                    total=0.0,
                    from_date=hour_key,
                    to_date=hour_key + timedelta(hours=1),
                )

            current = hourly_sums[hour_key]
            current.day += consumption.day
            current.night += consumption.night
            current.total += consumption.total

        # Round the final values
        for data in hourly_sums.values():
            data.day = data.day
            data.night = data.night
            data.total = data.total

        return hourly_sums

    async def _insert_statistics(self, consumptions: list[ConsumptionData]) -> None:
        if not consumptions:
            _LOGGER.debug("No consumption data to process")
            return

        # Define statistic IDs and their corresponding properties
        stat_configs = {
            DAY_CONSUMPTION_KEY: ("day", f"{DOMAIN} Day Consumption"),
            NIGHT_CONSUMPTION_KEY: ("night", f"{DOMAIN} Night Consumption"),
            TOTAL_CONSUMPTION_KEY: ("total", f"{DOMAIN} Total Consumption"),
        }

        # Get last statistics time in a single query
        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, TOTAL_CONSUMPTION_KEY, True, set()
        )

        last_stats_time = (
            last_stat[TOTAL_CONSUMPTION_KEY][0]["start"] if last_stat else None
        )

        # Process hourly consumptions
        hourly_data = self._sum_hourly_consumptions(consumptions)
        sorted_hours = sorted(hourly_data.keys())

        # Prepare statistics batch processing
        statistics_batch = {stat_id: [] for stat_id in stat_configs}
        sums = {stat_id: 0.0 for stat_id in stat_configs}

        # Process each hour's data
        for hour in sorted_hours:
            if last_stats_time and hour.timestamp() <= last_stats_time:
                continue

            consumption = hourly_data[hour]

            # Update statistics for each metric in a single pass
            for stat_id, (prop_name, _) in stat_configs.items():
                value = consumption.get(prop_name)
                sums[stat_id] += value

                statistics_batch[stat_id].append(
                    StatisticData(
                        start=hour,
                        state=value,
                        sum=sums[stat_id],
                    )
                )

        # Batch insert statistics if we have new data
        if any(statistics_batch.values()):
            base_metadata = {
                "has_mean": False,
                "has_sum": True,
                "source": DOMAIN,
                "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
            }

            for stat_id, (_, name) in stat_configs.items():
                if statistics_batch[stat_id]:
                    metadata = StatisticMetaData(
                        statistic_id=stat_id,
                        name=name,
                        **base_metadata,
                    )
                    _LOGGER.debug(
                        "Adding %s statistics for %s",
                        len(statistics_batch[stat_id]),
                        name,
                    )
                    async_add_external_statistics(
                        self.hass, metadata, statistics_batch[stat_id]
                    )
        else:
            _LOGGER.debug("No new statistics to add")
