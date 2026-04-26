import logging
import re
from http.cookies import SimpleCookie
from html import unescape
from urllib.parse import urljoin
from datetime import datetime
from typing import Any, Dict, Optional, List

import aiohttp
from pydantic import BaseModel, Field
from yarl import URL

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
    LOGIN_URL = "https://energybuddy.ail.ch/it/Security/login?BackURL=%2Fit%2Fbase"
    LOGIN_FORM_URL = "https://energybuddy.ail.ch/it/Security/LoginForm"
    BASE_URL = "https://energybuddy.ail.ch/it/base"
    ACCOUNT_URL = "https://account.ail.ch"

    def __init__(
        self,
        email: str,
        password: str,
        session_state: Optional[Dict[str, Any]] = None,
    ):
        self.email = email
        self.password = password
        self.token = None
        self._meter_id = None
        self.session = None
        self._session_state = session_state or {}
        self._pending_mfa_action = None
        self._pending_mfa_field = None
        self._pending_mfa_referer = None
        self._headers = {
            "Cache-Control": "no-cache, max-age=0, must-revalidate",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        }
        self._restore_auth_state()

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self._headers)
        self._restore_session_cookies()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def login(self) -> bool:
        await self._ensure_session()

        if await self._refresh_session_state():
            return True

        async with self.session.get(self.LOGIN_URL, allow_redirects=True):
            pass

        oauth_redirect = await self._start_oauth_login()
        if not oauth_redirect:
            return False

        keycloak_form = await self._get_keycloak_form_action(oauth_redirect)
        if not keycloak_form:
            return False

        auth_result = await self._submit_keycloak_credentials(
            keycloak_form, oauth_redirect
        )
        if not auth_result:
            return False

        final_url, content = auth_result
        if self._update_pending_mfa(content, final_url):
            return False

        return self._store_auth_state_from_content(content)

    async def _start_oauth_login(self) -> Optional[str]:
        login_payload = {
            "AuthenticationMethod": "OAuth2Authenticator",
            "action_dologin": "Accedi o crea un account AIL",
        }

        async with self.session.post(
            self.LOGIN_FORM_URL,
            data=login_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=False,
        ) as response:
            if response.status not in (302, 303):
                return None

            return response.headers.get("Location")

    async def _get_keycloak_form_action(self, auth_url: str) -> Optional[str]:
        async with self.session.get(auth_url, allow_redirects=True) as response:
            if response.status != 200:
                return None

            content = await response.text()

        match = re.search(
            r'<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"',
            content,
            re.IGNORECASE,
        )
        if not match:
            return None

        return urljoin(auth_url, unescape(match.group(1)))

    async def _submit_keycloak_credentials(
        self, form_action: str, referer: str
    ) -> Optional[tuple[str, str]]:
        login_payload = self._build_keycloak_login_payload()

        async with self.session.post(
            form_action,
            data=login_payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": referer,
            },
            allow_redirects=True,
        ) as response:
            if response.status != 200:
                return None

            return str(response.url), await response.text()

    async def submit_mfa_code(self, code: str) -> bool:
        """Submit the pending MFA step and complete login."""
        if not self._pending_mfa_action or not self._pending_mfa_field:
            raise ValueError("MFA is not pending")

        await self._ensure_session()
        async with self.session.post(
            self._pending_mfa_action,
            data={self._pending_mfa_field: code},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": self._pending_mfa_referer or self._pending_mfa_action,
            },
            allow_redirects=True,
        ) as response:
            if response.status != 200:
                return False

            final_url = str(response.url)
            content = await response.text()

        if self._update_pending_mfa(content, final_url):
            return False

        self._clear_pending_mfa()
        return self._store_auth_state_from_content(content)

    def is_mfa_pending(self) -> bool:
        """Return whether the login flow is waiting for an MFA code."""
        return bool(self._pending_mfa_action and self._pending_mfa_field)

    def export_session_state(self) -> Dict[str, Any]:
        """Serialize the current auth/session state for config entry storage."""
        cookies = []
        if self.session:
            for morsel in self.session.cookie_jar:
                cookies.append(
                    {
                        "name": morsel.key,
                        "value": morsel.value,
                        "domain": morsel["domain"] or "",
                        "path": morsel["path"] or "/",
                    }
                )

        return {
            "token": self.token,
            "meter_id": self._meter_id,
            "cookies": cookies,
        }

    async def _ensure_session(self) -> None:
        """Create the HTTP session lazily and restore persisted cookies."""
        if not self.session:
            self.session = aiohttp.ClientSession(headers=self._headers)
            self._restore_session_cookies()

    async def _refresh_session_state(self) -> bool:
        """Try to reuse an existing authenticated session before logging in again."""
        async with self.session.get(self.BASE_URL, allow_redirects=True) as response:
            if response.status != 200:
                return False

            content = await response.text()

        return self._store_auth_state_from_content(content)

    def _store_auth_state_from_content(self, content: str) -> bool:
        """Extract and persist token/meter from a logged-in page."""
        token = self._extract_token(content)
        meter_id = self._extract_meter_id(content)
        if not token or not meter_id:
            return False

        self.token = token
        self._meter_id = meter_id
        self._session_state = self.export_session_state()
        return True

    def _update_pending_mfa(self, content: str, current_url: str) -> bool:
        """Capture the MFA form details when Keycloak asks for a second step."""
        form_match = re.search(r'<form[^>]+action="([^"]+)"', content, re.IGNORECASE)
        input_tags = re.findall(r"<input\b[^>]*>", content, re.IGNORECASE)
        if not form_match or not input_tags:
            self._clear_pending_mfa()
            return False

        code_field = None
        for input_tag in input_tags:
            name_match = re.search(r'name="([^"]+)"', input_tag, re.IGNORECASE)
            if not name_match:
                continue

            type_match = re.search(r'type="([^"]*)"', input_tag, re.IGNORECASE)
            name = name_match.group(1)
            input_type = type_match.group(1).lower() if type_match else "text"
            input_type = input_type.lower() or "text"
            if input_type in {"text", "number", "tel", "password"} and name not in {
                "username",
                "password",
            }:
                code_field = name
                break

        if not code_field:
            self._clear_pending_mfa()
            return False

        self._pending_mfa_action = urljoin(current_url, unescape(form_match.group(1)))
        self._pending_mfa_field = code_field
        self._pending_mfa_referer = current_url
        return True

    def _clear_pending_mfa(self) -> None:
        """Reset any MFA state from a previous login attempt."""
        self._pending_mfa_action = None
        self._pending_mfa_field = None
        self._pending_mfa_referer = None

    def _restore_auth_state(self) -> None:
        """Restore cached token and meter identifiers."""
        self.token = self._session_state.get("token")
        self._meter_id = self._session_state.get("meter_id")

    def _restore_session_cookies(self) -> None:
        """Restore persisted cookies into the current aiohttp session."""
        if not self.session:
            return

        for cookie_data in self._session_state.get("cookies", []):
            cookie = SimpleCookie()
            cookie[cookie_data["name"]] = cookie_data["value"]
            if cookie_data.get("domain"):
                cookie[cookie_data["name"]]["domain"] = cookie_data["domain"]
            if cookie_data.get("path"):
                cookie[cookie_data["name"]]["path"] = cookie_data["path"]
            domain = cookie_data.get("domain", "").lstrip(".") or URL(self.BASE_URL).host
            self.session.cookie_jar.update_cookies(
                cookie, response_url=URL.build(scheme="https", host=domain)
            )

    def _build_keycloak_login_payload(
        self,
    ) -> Dict[str, str]:
        """Build the Keycloak login payload with remember-me enabled."""
        return {
            "username": self.email,
            "password": self.password,
            "credentialId": "",
            "login": "ACCEDI",
            "rememberMe": "on",
        }

    @staticmethod
    def _extract_token(content: str) -> Optional[str]:
        patterns = (
            r'aWattgarde\.config\.token\s*=\s*"([^"]+)"',
            r'"appToken":"([^"]+)"',
        )
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _extract_meter_id(content: str) -> Optional[str]:
        patterns = (
            r'SelectedMeterID["\']?\s*[:=]\s*["\']?(\d+)',
            r'aWattgarde\.Page\.SelectedMeterID\s*=\s*["\']?(\d+)',
            r'"meterID"\s*:\s*"?(\d+)"?',
            r'"ID":\s*(\d+)',
        )
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)
        return None

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
