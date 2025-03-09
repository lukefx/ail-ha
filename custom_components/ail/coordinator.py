import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_client import AILEnergyClient, ConsumptionResponse
from .const import (
    DOMAIN,
    ENERGY_NIGHT_CONSUMPTION_KEY,
    ENERGY_DAY_CONSUMPTION_KEY,
    ENERGY_CONSUMPTION_KEY,
    DEFAULT_UPDATE_INTERVAL_HOUR,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class ConsumptionData:
    """Class for holding consumption data."""

    day: float
    night: float
    from_date: datetime
    to_date: datetime
    tickers: int = 0

    def get(self, property_name: str) -> Any:
        """Get property value by name."""
        return getattr(self, property_name)

    @property
    def total(self) -> float:
        """Total consumption (day + night)."""
        return self.day + self.night

    @classmethod
    def from_api_response(cls, data: ConsumptionResponse) -> List["ConsumptionData"]:
        """Create ConsumptionData objects from API response.

        Args:
            data: The API response containing consumption records

        Returns:
            List of ConsumptionData objects
        """
        statistics = []
        for record in data.response:
            # Skip records with no readings
            if record.readings_count is not None and record.readings_count > 0:
                statistics.append(
                    cls(
                        day=record.day,
                        night=record.night,
                        from_date=record.from_,
                        to_date=record.to,
                    )
                )
        return statistics


class EnergyDataUpdateCoordinator(DataUpdateCoordinator[Optional[ConsumptionData]]):
    """Class to manage fetching data from the API and updating statistics."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: AILEnergyClient
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: The Home Assistant instance
            entry: The config entry
            client: The AIL Energy API client
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # Ping the api every hour, so we provide the data as sensor, and we try to add statistic
            update_interval=timedelta(hours=DEFAULT_UPDATE_INTERVAL_HOUR),
        )
        self.api_client = client
        self.entry = entry

    async def _async_setup(self) -> None:
        """Set up the coordinator by fetching historical data.

        Raises:
            ConfigEntryAuthFailed: If authentication fails
        """
        _LOGGER.info("Setting up AIL Energy coordinator")

        # Check if we already have statistics
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, ENERGY_CONSUMPTION_KEY, True, set()
        )

        if not last_stats:
            _LOGGER.info("No statistics found, fetching historical data")
            await self._fetch_historical_data()
        else:
            _LOGGER.info("Statistics already exist, skipping historical data fetch")

    async def _async_update_data(self) -> Optional[ConsumptionData]:
        """Update data via API and update statistics.

        Returns:
            The latest consumption data or None if no data is available

        Raises:
            ConfigEntryAuthFailed: If authentication fails
            UpdateFailed: If data cannot be fetched or processed
        """
        if not await self.api_client.login():
            raise ConfigEntryAuthFailed

        _from = datetime.now() - timedelta(days=4)
        _to = datetime.now()
        response = await self.api_client.get_consumption_data(_from, _to)
        consumption_data = ConsumptionData.from_api_response(response)
        _LOGGER.debug("Updated consumption data: %s", consumption_data)

        # Process hourly consumptions
        hourly_data = self._sum_hourly_consumptions(consumption_data)

        # Handle empty consumption_stats array
        if not hourly_data:
            _LOGGER.warning("No consumption data received from API")
            return None

        await self._insert_statistics(hourly_data)

        # Return the most recent consumption data if available
        if consumption_data:
            return consumption_data[-1]
        return None

    async def _fetch_historical_data(self) -> None:
        """Fetch historical data for the past 90 days.

        Raises:
            ConfigEntryAuthFailed: If authentication fails
        """
        # Fetch historical data for the last 3 months in smaller chunks
        end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = end_date - timedelta(days=90)  # last 3 months

        chunk_size = timedelta(days=4)
        chunk_start = start_date

        if not await self.api_client.login():
            raise ConfigEntryAuthFailed

        all_consumption_data: Dict[datetime, ConsumptionData] = {}
        while chunk_start < end_date:
            chunk_end = min(chunk_start + chunk_size, end_date)
            _LOGGER.debug("Fetching data from %s to %s", chunk_start, chunk_end)
            try:
                response = await self.api_client.get_consumption_data(
                    chunk_start, chunk_end
                )
                consumption_data = ConsumptionData.from_api_response(response)
                hourly_data = self._sum_hourly_consumptions(consumption_data)
                _LOGGER.debug("Found %d hourly records", len(hourly_data))
                all_consumption_data.update(hourly_data)
            except Exception as err:
                _LOGGER.error(
                    "Error fetching chunk %s to %s: %s", chunk_start, chunk_end, err
                )
            # Move to next chunk regardless of success to try to get as much data as possible
            chunk_start = chunk_end

        if all_consumption_data:
            _LOGGER.info(
                "Inserting %d historical data points", len(all_consumption_data)
            )
            await self._insert_statistics(all_consumption_data)
        else:
            _LOGGER.warning("No historical consumption data was retrieved")

    @staticmethod
    def _sum_hourly_consumptions(
        consumptions: List[ConsumptionData],
    ) -> Dict[datetime, ConsumptionData]:
        """Sum consumption records into hourly buckets.

        Args:
            consumptions: List of consumption data records

        Returns:
            Dictionary mapping hour start times to summed consumption data
        """
        if not consumptions:
            return {}

        hourly_sums: Dict[datetime, ConsumptionData] = {}
        for consumption in consumptions:
            hour_key = consumption.from_date.replace(minute=0, second=0, microsecond=0)
            if hour_key not in hourly_sums:
                hourly_sums[hour_key] = ConsumptionData(
                    day=0.0,
                    night=0.0,
                    from_date=hour_key,
                    to_date=hour_key + timedelta(hours=1),
                    tickers=0,
                )

            current = hourly_sums[hour_key]

            # between 00:00 and 07:00 is considered night (off-peak hours)
            # between 07:00 and 00:00 is considered day (peak hours)
            if 0 <= current.from_date.hour < 7 and 0 <= current.to_date.hour <= 7:
                current.night += consumption.day
            else:
                current.day += consumption.day
            current.tickers += 1

        # filter all hours that have less than 4 tickers (ensures complete data)
        return {k: v for k, v in hourly_sums.items() if v.tickers >= 4}

    async def _insert_statistics(
        self, consumptions: Dict[datetime, ConsumptionData]
    ) -> None:
        """Insert consumption data into Home Assistant statistics.

        Args:
            consumptions: Dictionary mapping hour start times to consumption data
        """
        if not consumptions:
            _LOGGER.debug("No consumption data to process")
            return

        # Process day and night consumption separately
        await self._insert_statistic_type(
            consumptions, "day", ENERGY_DAY_CONSUMPTION_KEY, "Energy consumption (day)"
        )
        await self._insert_statistic_type(
            consumptions,
            "night",
            ENERGY_NIGHT_CONSUMPTION_KEY,
            "Energy consumption (night)",
        )
        await self._insert_statistic_type(
            consumptions,
            "total",
            ENERGY_CONSUMPTION_KEY,
            "Energy consumption (total)",
        )

    async def _insert_statistic_type(
        self,
        consumptions: Dict[datetime, ConsumptionData],
        data_type: str,
        statistic_id: str,
        name: str,
    ) -> None:
        """Insert a specific type of statistic (day/night) into Home Assistant.

        Args:
            consumptions: Dictionary mapping hour start times to consumption data
            data_type: The type of data to insert ("day", "night" or "total")
            statistic_id: The statistic ID to use
            name: The display name for the statistic
        """
        # Get last statistics time in a single query
        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        last_stats_time = (
            last_stat[statistic_id][0]["start"]
            if last_stat and statistic_id in last_stat
            else None
        )

        base_metadata = {
            "has_mean": False,
            "has_sum": True,
            "source": DOMAIN,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        }

        sum_value = (
            last_stat[statistic_id][0]["sum"]
            if last_stat and statistic_id in last_stat
            else 0.0
        )
        statistics = []

        # Prepare statistics for each hour
        for hour, consumption in consumptions.items():
            # Skip hours that are already processed
            if last_stats_time and hour.timestamp() <= last_stats_time:
                continue

            value = getattr(consumption, data_type)
            sum_value += value
            statistics.append(
                StatisticData(
                    start=hour,
                    state=value,
                    sum=sum_value,
                )
            )

        if statistics:
            metadata = StatisticMetaData(
                statistic_id=statistic_id,
                name=name,
                **base_metadata,
            )
            async_add_external_statistics(self.hass, metadata, statistics)
            _LOGGER.debug("Added %d statistics for %s", len(statistics), name)
