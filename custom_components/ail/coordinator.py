import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

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

    def get(self, property_name: str) -> any:
        """Get property value by name."""
        return getattr(self, property_name)

    @classmethod
    def from_api_response(cls, data: dict) -> list["ConsumptionData"]:
        """Create instance from API response."""
        if not data.get("response") or len(data["response"]) < 1:
            raise ValueError("API response must contain exactly one consumption record")
        response = data["response"]
        statistics = []
        for item in response:
            statistics.append(
                cls(
                    day=item.get("day", 0),
                    night=item.get("night", 0),
                    from_date=datetime.fromisoformat(item["from"]),
                    to_date=datetime.fromisoformat(item["to"]),
                    total=item.get("day", 0) + item.get("night", 0),
                )
            )
        return statistics


class EnergyDataUpdateCoordinator(DataUpdateCoordinator[ConsumptionData]):
    """Class to manage fetching data from the API and updating statistics."""

    def __init__(self, hass: HomeAssistant, client: AILEnergyClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=12),
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
            _from = datetime.now() - timedelta(days=2)
            _to = datetime.now() - timedelta(days=1)
            raw_data = await self.api_client.get_consumption_data(_from, _to)
            consumption_stats = ConsumptionData.from_api_response(raw_data)
            _LOGGER.debug("Updated consumption data: %s", consumption_stats)

            # Update statistics after getting new data
            await self._insert_statistics(consumption_stats)
            return consumption_stats
        except Exception as err:
            _LOGGER.error("Error fetching consumption data: %s", err)
            raise UpdateFailed(f"Error updating data: {err}") from err

    def sum_hourly_consumptions(
        self, consumptions: list[ConsumptionData]
    ) -> list[ConsumptionData]:
        """Sum consumption data by hour.

        Args:
            consumptions: List of consumption data records

        Returns:
            List of ConsumptionData objects with hourly sums
        """
        hourly_sums = []
        current_hour = None
        current_day_sum = 0.0
        current_night_sum = 0.0
        current_total_sum = 0.0

        for consumption in consumptions:
            consumption_hour = consumption.from_date.replace(
                minute=0, second=0, microsecond=0
            )

            if current_hour != consumption_hour:
                # Save the previous hour's sums if they exist
                if current_hour is not None:
                    hourly_sums.append(
                        ConsumptionData(
                            day=round(current_day_sum, 2),
                            night=round(current_night_sum, 2),
                            total=round(current_total_sum, 2),
                            from_date=current_hour,
                            to_date=current_hour + timedelta(hours=1),
                        )
                    )
                # Reset for the new hour
                current_hour = consumption_hour
                current_day_sum = 0.0
                current_night_sum = 0.0
                current_total_sum = 0.0

            # Add consumption values for the current hour
            current_day_sum += consumption.day
            current_night_sum += consumption.night
            current_total_sum += consumption.total

        # Add the last hour's sums if they exist
        if current_hour is not None:
            hourly_sums.append(
                ConsumptionData(
                    day=round(current_day_sum, 2),
                    night=round(current_night_sum, 2),
                    total=round(current_total_sum, 2),
                    from_date=current_hour,
                    to_date=current_hour + timedelta(hours=1),
                )
            )

        return hourly_sums

    async def _insert_statistics(self, consumptions: list[ConsumptionData]) -> None:
        """Insert energy consumption statistics.

        Args:
            consumptions: List of consumption data records to process
        """
        if not consumptions:
            _LOGGER.debug("No consumption data to process")
            return

        # Define base statistic IDs
        day_statistic_id = f"{DOMAIN}:energy_day_consumption"
        night_statistic_id = f"{DOMAIN}:energy_night_consumption"
        total_statistic_id = f"{DOMAIN}:energy_total_consumption"

        _LOGGER.debug(
            "Updating Statistics for day: %s, night: %s, total: %s",
            day_statistic_id,
            night_statistic_id,
            total_statistic_id,
        )

        # Get last statistics to determine our starting point
        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, total_statistic_id, True, set()
        )

        if not last_stat:
            _LOGGER.debug("Updating statistics for the first time")
            day_sum = night_sum = total_sum = 0.0
            last_stats_time = None
        else:
            # Get the earliest consumption date to use as our start time
            start = min(c.from_date for c in consumptions)
            _LOGGER.debug("Getting statistics at: %s", start)

            # Try to find existing statistics at the start time
            # If none found at exact time, try to find the oldest after start
            for end in (start + timedelta(seconds=1), None):
                stats = await get_instance(self.hass).async_add_executor_job(
                    statistics_during_period,
                    self.hass,
                    start,
                    end,
                    {day_statistic_id, night_statistic_id, total_statistic_id},
                    "hour",
                    None,
                    {"sum"},
                )
                if stats:
                    break
                if end:
                    _LOGGER.debug(
                        "Not found. Trying to find the oldest statistic after %s",
                        start,
                    )

            # Initialize sums from existing statistics if found
            if not stats:
                day_sum = night_sum = total_sum = 0.0
                last_stats_time = None
            else:
                day_sum = float(stats[day_statistic_id][0]["sum"])
                night_sum = float(stats[night_statistic_id][0]["sum"])
                total_sum = float(stats[total_statistic_id][0]["sum"])
                last_stats_time = stats[total_statistic_id][0]["start"]

        # Initialize statistics lists
        day_statistics = []
        night_statistics = []
        total_statistics = []

        # Sort consumptions by date to ensure proper sum calculation
        consumptions = self.sum_hourly_consumptions(consumptions)
        sorted_consumptions = sorted(consumptions, key=lambda x: x.from_date)

        # Process each consumption record
        for consumption in sorted_consumptions:
            start = consumption.from_date

            # Skip if this consumption period has already been recorded
            if last_stats_time is not None and start.timestamp() <= last_stats_time:
                continue

            # Update running sums
            day_sum += consumption.day
            night_sum += consumption.night
            total_sum += consumption.total

            # Create statistics records
            day_statistics.append(
                StatisticData(
                    start=start,
                    state=consumption.day,
                    sum=day_sum,
                )
            )
            night_statistics.append(
                StatisticData(
                    start=start,
                    state=consumption.night,
                    sum=night_sum,
                )
            )
            total_statistics.append(
                StatisticData(
                    start=start,
                    state=consumption.total,
                    sum=total_sum,
                )
            )

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

        # Add statistics to the database if we have new data
        if day_statistics:
            _LOGGER.debug(
                "Adding %s statistics for day consumption",
                len(day_statistics),
            )
            async_add_external_statistics(self.hass, day_metadata, day_statistics)

            _LOGGER.debug(
                "Adding %s statistics for night consumption",
                len(night_statistics),
            )
            async_add_external_statistics(self.hass, night_metadata, night_statistics)

            _LOGGER.debug(
                "Adding %s statistics for total consumption",
                len(total_statistics),
            )
            async_add_external_statistics(self.hass, total_metadata, total_statistics)
        else:
            _LOGGER.debug("No new statistics to add")
