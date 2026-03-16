from __future__ import annotations

import contextlib
import logging
import asyncio
import random
import json
import httpx

from typing import TYPE_CHECKING, Any, Self

from .const import (
    AQUALINK_API_KEY,
    AQUALINK_DEVICES_URL,
    AQUALINK_LOGIN_URL,
    KEEPALIVE_EXPIRY,
)
from .exception import (
    AqualinkServiceException,
    AqualinkServiceUnauthorizedException,
    AqualinkSystemUnsupportedException,
)
from .system import AqualinkSystem
from .systems.exo import system as exo_system
from .systems.iaqua import system as iaqua_system

if TYPE_CHECKING:
    from types import TracebackType

AQUALINK_HTTP_HEADERS = {
    "user-agent": "okhttp/3.14.7",
    "content-type": "application/json",
}

_LOGGER = logging.getLogger(__name__)


def _resp_status(resp: Any) -> int | None:
    return getattr(resp, "status_code", None) or getattr(resp, "status", None)

async def _resp_text(resp: Any) -> str:
    # httpx: .text is a property
    if hasattr(resp, "text") and not callable(getattr(resp, "text")):
        return resp.text  # type: ignore[attr-defined]
    # aiohttp/HA: .text() is coroutine
    if hasattr(resp, "text") and callable(getattr(resp, "text")):
        return await resp.text()  # type: ignore[misc]
    return ""

async def _resp_json(resp: Any) -> Any:
    # httpx: .json() sync
    if hasattr(resp, "json") and callable(getattr(resp, "json")):
        try:
            return resp.json()
        except TypeError:
            # aiohttp/HA: .json() async
            return await resp.json()
    # fallback
    txt = await _resp_text(resp)
    try:
        return json.loads(txt)
    except Exception:
        return {}

class AqualinkClient:
    def __init__(
        self,
        username: str,
        password: str,
        httpx_client: httpx.AsyncClient,
    ) -> None:
        self._username = username
        self._password = password
        self._logged = False

        # Home Assistant-managed shared client
        self._client: httpx.AsyncClient = httpx_client
        self._must_close_client = False

        self.client_id = ""
        self._token = ""
        self._user_id = ""
        self.id_token = ""

        self._last_refresh = 0

    @property
    def logged(self) -> bool:
        return self._logged

    async def close(self) -> None:
        #Close client if owned by this instance.
        if self._must_close_client and self._client is not None:
            await self._client.aclose()
            self._client = None


    async def __aenter__(self) -> Self:
        try:
            await self.login()
        except AqualinkServiceException:
            #await self.close()
            raise

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        await self.close()
        return exc is None


    async def send_request(self, url: str, method: str = "get", **kwargs: Any) -> Any:
        #HTTP request with retries (401 relogin, 429 backoff, network retry).
    
        max_retries = 6
        base_delay = 5
        max_delay = 60
    
        last_exc: Exception | None = None
    
        # IMPORTANT: extract extra headers once, outside retry loop
        extra_headers = kwargs.pop("headers", {}) or {}
    
        if self._client is None:
            raise AqualinkServiceException("HTTP client is not initialized")

    
        for attempt in range(1, max_retries + 1):
            # rebuild headers at every attempt
            headers = AQUALINK_HTTP_HEADERS.copy()
            headers.update(extra_headers)
    
            try:
                _LOGGER.debug("iAQUALINK_eXO-IQ -> %s %s %s", method.upper(), url, kwargs)
                r = await self._client.request(method, url, headers=headers, **kwargs)
    
                status = _resp_status(r)
                reason = getattr(r, "reason_phrase", "")
                _LOGGER.debug("iAQUALINK_eXO-IQ <- %s %s - %s", status, reason, url)
    
                # 401 Unauthorized => relogin then retry
                if status == 401:
                    last_exc = AqualinkServiceUnauthorizedException(f"401 on {url}")
                    self._logged = False
                    _LOGGER.warning(
                        "iAQUALINK_eXO-IQ - 401 Unauthorized on %s (attempt %s/%s) -> re-login",
                        url, attempt, max_retries
                    )
    
                    if attempt >= max_retries:
                        raise last_exc
    
                    await self.login()
    
                    # IMPORTANT: refresh Authorization header for next retry
                    if "Authorization" in extra_headers:
                        extra_headers["Authorization"] = self.id_token
    
                    continue
    
                # 429 Too Many Requests => backoff then retry
                if status == 429:
                    last_exc = AqualinkServiceException(f"429 rate limited on {url}")
    
                    headers_obj = getattr(r, "headers", {}) or {}
                    retry_after_hdr = headers_obj.get("Retry-After")
    
                    if retry_after_hdr is not None:
                        try:
                            sleep_s = int(float(retry_after_hdr))
                        except ValueError:
                            sleep_s = base_delay
                        _LOGGER.warning(
                            "iAQUALINK_eXO-IQ - Rate limited (429). Retry-After=%s -> sleeping %ss",
                            retry_after_hdr, sleep_s
                        )
                    else:
                        sleep_s = min(base_delay * (2 ** (attempt - 1)), max_delay)
                        sleep_s = sleep_s + random.uniform(0, 1.0)
                        _LOGGER.warning(
                            "iAQUALINK_eXO-IQ - Rate limited (429). sleeping %.1fs (attempt %s/%s)",
                            sleep_s, attempt, max_retries
                        )
    
                    if attempt >= max_retries:
                        raise last_exc
    
                    await asyncio.sleep(sleep_s)
                    continue
    
                # Other HTTP errors
                if hasattr(r, "raise_for_status") and callable(getattr(r, "raise_for_status")):
                    r.raise_for_status()
                else:
                    if status is not None and status >= 400:
                        body = await _resp_text(r)
                        raise AqualinkServiceException(f"HTTP {status} on {url}: {body}")
    
                return r
    
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                sleep_s = min(base_delay * (2 ** (attempt - 1)), max_delay)
                sleep_s = sleep_s + random.uniform(0, 1.0)
                _LOGGER.warning(
                    "iAQUALINK_eXO-IQ - HTTP transient error (%s) on %s -> sleeping %.1fs (attempt %s/%s)",
                    type(e).__name__, url, sleep_s, attempt, max_retries
                )
                if attempt >= max_retries:
                    break
                await asyncio.sleep(sleep_s)
                continue
    
            except httpx.HTTPStatusError as e:
                last_exc = e
                st = _resp_status(e.response)
                _LOGGER.error("iAQUALINK_eXO-IQ - HTTP error %s on %s: %s", st, url, e)
                raise AqualinkServiceException(str(e)) from e
    
            except Exception as e:
                last_exc = e
                _LOGGER.error("iAQUALINK_eXO-IQ - Unexpected error calling %s: %s", url, e)
                raise AqualinkServiceException(str(e)) from e
    
        raise AqualinkServiceException(
            f"Failed after retries calling {url} (last_exc={last_exc!r})"
        ) from last_exc


    async def _send_login_request(self) -> httpx.Response:
        data = {
            "api_key": AQUALINK_API_KEY,
            "email": self._username,
            "password": self._password,
        }
        return await self.send_request(AQUALINK_LOGIN_URL, method="post", json=data)

    async def login(self) -> None:
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                r = await self._send_login_request()
                data = await _resp_json(r)
                self.client_id = data["session_id"]
                self._token = data["authentication_token"]
                self._user_id = data["id"]
                self.id_token = data["userPoolOAuth"]["IdToken"]
                self._logged = True
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                _LOGGER.warning("iAQUALINK_eXO-IQ - Login failed, retrying in %s seconds... (%s)", retry_delay, e)
                await asyncio.sleep(retry_delay)

    async def _send_systems_request(self) -> httpx.Response:
        params = {
            "api_key": AQUALINK_API_KEY,
            "authentication_token": self._token,
            "user_id": self._user_id,
        }
        params_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{AQUALINK_DEVICES_URL}?{params_str}"
        return await self.send_request(url)

    async def get_systems(self) -> dict[str, AqualinkSystem]:
        try:
            r = await self._send_systems_request()
        except AqualinkServiceException as e:
            if "404" in str(e):
                raise AqualinkServiceUnauthorizedException from e
            raise

        data = await _resp_json(r)

        systems: list[AqualinkSystem] = []
        for x in data:
            with contextlib.suppress(AqualinkSystemUnsupportedException):
                systems += [AqualinkSystem.from_data(self, x)]

        return {x.serial: x for x in systems if x is not None}