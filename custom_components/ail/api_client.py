import logging
import re
from datetime import datetime
from typing import Optional, List

import aiohttp
from pydantic import BaseModel, Field

_LOGGER = logging.getLogger(__name__)


class ConsumptionRecord(BaseModel):
    """Model for a single consumption record."""

    day: Optional[float] = 0.0
    from_: datetime = Field(..., alias="from")
    to: datetime
    is_pending: bool = Field(..., alias="isPending")
    readings_count: Optional[int] = Field(None, alias="readingsCount")
    night: Optional[float] = 0.0


class ConsumptionResponse(BaseModel):
    """Model for the complete API response."""

    response: List[ConsumptionRecord]

    class Config:
        allow_population_by_field_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


class AILEnergyClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.token = None
        self._meter_id = None
        self.session = None
        self._headers = {
            "Cache-Control": "no-cache, max-age=0, must-revalidate",
            "Location": "/it/base",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        }

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self._headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def login(self) -> bool:
        if not self.session:
            self.session = aiohttp.ClientSession(headers=self._headers)

        login_payload = {
            "AuthenticationMethod": "CustomMemberAuthenticator",
            "Email": self.email,
            "Password": self.password,
            "action_dologin": "Accedi",
        }

        async with self.session.post(
            "https://energybuddy.ail.ch/it/Security/LoginForm",
            data=login_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=True,
        ) as response:
            if response.status == 200:
                content = await response.text()

                token_match = re.search(
                    r'aWattgarde\.config\.token\s*=\s*"([^"]+)"', content
                )
                if token_match:
                    self.token = token_match.group(1)

                meter_match = re.search(r'"ID":\s*(\d+)', content)
                if meter_match:
                    self._meter_id = meter_match.group(1)

                if self.token and self._meter_id:
                    return True

            return False

    def get_meter_id(self) -> Optional[str]:
        return self._meter_id

    async def get_consumption_data(
        self, _from: datetime, _to: datetime
    ) -> ConsumptionResponse:
        _LOGGER.debug(f"Calling API for timedelta {_from} -> {_to}...")

        if not self.token:
            raise ValueError("Not logged in. Call login() first")

        payload = {
            "meterID": self._meter_id,
            "scale": "hours",
            "timeFrame": {
                "from": _from.strftime("%Y-%m-%d %H:%M:%S"),
                "to": _to.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "forceWholeTimeFrame": False,
            "hoursPrecision": True,
            "fetchPreviousYearData": False,
        }

        params = {"token": self.token}
        async with self.session.post(
            "https://energybuddy.ail.ch/api/v2/service/MeterService/getReadingsByScaleAndTimeRange",
            params=params,
            json=payload,
        ) as response:
            if response.status == 200:
                raw_json = await response.json()
                return ConsumptionResponse(**raw_json)
            else:
                raise ConnectionError(
                    f"Request failed with status code: {response.status}"
                )
