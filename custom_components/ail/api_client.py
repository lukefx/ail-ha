import json
import logging
import math
import re
from http.cookies import SimpleCookie
from html import unescape
from urllib.parse import urljoin
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, List

import aiohttp
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from yarl import URL

_LOGGER = logging.getLogger(__name__)

APPROVED_HOSTS = frozenset({"energybuddy.ail.ch", "account.ail.ch"})
MAX_REDIRECTS = 8
MAX_HTML_BYTES = 1_000_000
MAX_JSON_BYTES = 2_000_000
MAX_RECORDS = 3_000
HTTP_TIMEOUT = aiohttp.ClientTimeout(
    total=30, connect=10, sock_connect=10, sock_read=20
)


class AILClientError(Exception):
    """Safe client error that does not include URLs or credentials."""


def validate_ail_url(value: str, *, base: str | None = None) -> str:
    """Resolve and validate an AIL URL before issuing a request."""
    try:
        url = URL(urljoin(base, value) if base else value)
    except (TypeError, ValueError) as err:
        raise AILClientError("AIL returned an invalid URL") from err

    if url.scheme != "https" or url.host not in APPROVED_HOSTS:
        raise AILClientError("AIL returned an unapproved destination")
    if url.user is not None or url.password is not None or url.port != 443:
        raise AILClientError("AIL returned unsafe URL authority data")

    return str(url)


def _validate_energy(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("invalid energy value")
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError) as err:
        raise ValueError("invalid energy value") from err
    if not math.isfinite(result) or result < 0:
        raise ValueError("invalid energy value")
    return result


class ConsumptionRecord(BaseModel):
    """Model for a single consumption record."""

    day: Optional[float] = 0.0
    from_: datetime = Field(..., alias="from")
    to: datetime
    is_pending: bool = Field(..., alias="isPending")
    readings_count: Optional[int] = Field(None, alias="readingsCount")
    night: Optional[float] = 0.0

    @field_validator("day", "night", mode="before")
    @classmethod
    def validate_energy(cls, value: Any) -> float:
        return _validate_energy(value)

    @field_validator("from_", "to")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if not 2000 <= value.year <= datetime.now(timezone.utc).year + 1:
            raise ValueError("invalid timestamp")
        return value

    @field_validator("readings_count", mode="before")
    @classmethod
    def validate_readings_count(cls, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("invalid reading count")
        return value

    @model_validator(mode="after")
    def validate_interval(self) -> "ConsumptionRecord":
        if self.to <= self.from_ or self.to - self.from_ > timedelta(days=1):
            raise ValueError("invalid time interval")
        return self


class ConsumptionResponse(BaseModel):
    """Model for the complete API response."""

    response: List[ConsumptionRecord] = Field(max_length=MAX_RECORDS)

    class Config:
        allow_population_by_field_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


def parse_response(data: Any) -> ConsumptionResponse:
    """Validate an AIL consumption response without leaking its contents."""
    try:
        return ConsumptionResponse.model_validate(data)
    except ValidationError as err:
        raise AILClientError("AIL returned an invalid response") from err


class AILEnergyClient:
    LOGIN_URL = "https://energybuddy.ail.ch/it/Security/login?BackURL=%2Fit%2Fbase"
    LOGIN_FORM_URL = "https://energybuddy.ail.ch/it/Security/LoginForm"
    BASE_URL = "https://energybuddy.ail.ch/it/base"
    ACCOUNT_URL = "https://account.ail.ch"
    API_URL = "https://energybuddy.ail.ch/api/v2/service/MeterService/getReadingsByScaleAndTimeRange"

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
        self.session = aiohttp.ClientSession(
            headers=self._headers,
            timeout=HTTP_TIMEOUT,
        )
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

        await self._request("GET", self.LOGIN_URL)

        oauth_redirect = await self._start_oauth_login()
        current_url, content = await self._get_keycloak_page(oauth_redirect)
        if self._store_auth_state_from_content(content):
            return True

        keycloak_form = self._extract_keycloak_form_action(content, current_url)
        if not keycloak_form:
            raise AILClientError(
                "AIL returned neither an authenticated page nor a Keycloak login form"
            )

        auth_result = await self._submit_keycloak_credentials(
            keycloak_form, current_url
        )

        final_url, content = auth_result
        if self._update_pending_mfa(content, final_url):
            return False

        return self._store_auth_state_from_content(content)

    async def _start_oauth_login(self) -> str:
        login_payload = {
            "AuthenticationMethod": "OAuth2Authenticator",
            "action_dologin": "Accedi o crea un account AIL",
        }

        assert self.session is not None
        async with self.session.post(
            self.LOGIN_FORM_URL,
            data=login_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=False,
        ) as response:
            if response.status not in (302, 303):
                raise AILClientError(f"AIL OAuth start returned HTTP {response.status}")

            location = response.headers.get("Location")
            if not location:
                raise AILClientError("AIL OAuth start omitted the redirect location")
            return validate_ail_url(location, base=self.LOGIN_FORM_URL)

    async def _get_keycloak_page(self, auth_url: str) -> tuple[str, str]:
        """Fetch the identity-provider page after following silent SSO redirects."""
        current_url, body = await self._request("GET", auth_url)
        return current_url, body.decode("utf-8", "replace")

    @staticmethod
    def _extract_keycloak_form_action(content: str, current_url: str) -> Optional[str]:
        """Extract a credential form action from a Keycloak response."""
        match = re.search(
            r'<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"',
            content,
            re.IGNORECASE,
        )
        if not match:
            return None

        return validate_ail_url(unescape(match.group(1)), base=current_url)

    async def _submit_keycloak_credentials(
        self, form_action: str, referer: str
    ) -> tuple[str, str]:
        login_payload = self._build_keycloak_login_payload()

        final_url, body = await self._request(
            "POST",
            form_action,
            data=login_payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": referer,
            },
        )
        return final_url, body.decode("utf-8", "replace")

    async def submit_mfa_code(self, code: str) -> bool:
        """Submit the pending MFA step and complete login."""
        if not self._pending_mfa_action or not self._pending_mfa_field:
            raise ValueError("MFA is not pending")

        final_url, body = await self._request(
            "POST",
            validate_ail_url(self._pending_mfa_action),
            data={self._pending_mfa_field: code},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": self._pending_mfa_referer or self._pending_mfa_action,
            },
        )
        content = body.decode("utf-8", "replace")

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
                domain = (morsel["domain"] or "").lstrip(".").lower()
                if domain not in APPROVED_HOSTS:
                    continue
                cookies.append(
                    {
                        "name": morsel.key,
                        "value": morsel.value,
                        "domain": domain,
                        "path": morsel["path"] or "/",
                        "secure": bool(morsel["secure"]),
                        "httponly": bool(morsel["httponly"]),
                        "samesite": morsel["samesite"] or "",
                        "expires": morsel["expires"] or "",
                        "max-age": morsel["max-age"] or "",
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
            self.session = aiohttp.ClientSession(
                headers=self._headers,
                timeout=HTTP_TIMEOUT,
            )
            self._restore_session_cookies()

    async def _request(self, method: str, url: str, **kwargs: Any) -> tuple[str, bytes]:
        """Issue a bounded request while validating every redirect."""
        await self._ensure_session()
        current = validate_ail_url(url)

        for _ in range(MAX_REDIRECTS + 1):
            assert self.session is not None
            async with self.session.request(
                method,
                current,
                allow_redirects=False,
                **kwargs,
            ) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise AILClientError("AIL returned an incomplete redirect")
                    current = validate_ail_url(location, base=current)
                    if response.status in {301, 302, 303} and method != "GET":
                        method, kwargs = "GET", {}
                    continue

                if response.status != 200:
                    raise AILClientError("AIL request failed")

                limit = (
                    MAX_JSON_BYTES
                    if "json" in response.headers.get("Content-Type", "").lower()
                    else MAX_HTML_BYTES
                )
                if (
                    response.content_length is not None
                    and response.content_length > limit
                ):
                    raise AILClientError("AIL response was too large")
                body = await response.content.read(limit + 1)
                if len(body) > limit:
                    raise AILClientError("AIL response was too large")
                return validate_ail_url(str(response.url)), body

        raise AILClientError("AIL returned too many redirects")

    async def _refresh_session_state(self) -> bool:
        """Try to reuse an existing authenticated session before logging in again."""
        try:
            _, body = await self._request("GET", self.BASE_URL)
        except AILClientError:
            return False
        content = body.decode("utf-8", "replace")

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

        self._pending_mfa_action = validate_ail_url(
            unescape(form_match.group(1)), base=current_url
        )
        self._pending_mfa_field = code_field
        self._pending_mfa_referer = validate_ail_url(current_url)
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
            if not isinstance(cookie_data, dict):
                continue
            domain = (
                str(cookie_data.get("domain", "")).lstrip(".").lower()
                or URL(self.BASE_URL).host
            )
            if domain not in APPROVED_HOSTS or not cookie_data.get("secure", True):
                continue
            name = cookie_data.get("name")
            value = cookie_data.get("value")
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            cookie = SimpleCookie()
            cookie[name] = value
            cookie[name]["domain"] = domain
            cookie[name]["secure"] = True
            for attribute in ("path", "expires", "max-age", "samesite"):
                if cookie_data.get(attribute):
                    cookie[name][attribute] = cookie_data[attribute]
            if cookie_data.get("httponly"):
                cookie[name]["httponly"] = True
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

        _, body = await self._request(
            "POST",
            self.API_URL,
            params={"token": self.token},
            json=payload,
        )
        try:
            raw_json = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            raise AILClientError("AIL returned an invalid response") from err
        return parse_response(raw_json)
