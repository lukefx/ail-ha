import logging
import re
from datetime import datetime

import aiohttp

_LOGGER = logging.getLogger(__name__)


class AILEnergyClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.token = None
        self.meter_id = None
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
        if self.session:
            await self.session.close()

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
                    self.meter_id = meter_match.group(1)

                if self.token and self.meter_id:
                    return True

            return False

    async def get_consumption_data(self, _from: datetime, _to: datetime) -> dict:
        _LOGGER.debug("Calling API...")

        if not self.token:
            raise ValueError("Not logged in. Call login() first")

        payload = {
            "meterID": self.meter_id,
            "scale": "hours",
            "timeFrame": {
                "from": _from.strftime("%Y-%m-%d %H:%M:%S"),
                "to": _to.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "forceWholeTimeFrame": True,
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
                return await response.json()
            else:
                raise ConnectionError(
                    f"Request failed with status code: {response.status}"
                )
