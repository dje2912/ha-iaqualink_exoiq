"""Config flow for iAqualink integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
import httpx

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, KEEPALIVE_EXPIRY

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iAqualink."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            from .client import AqualinkClient

            httpx_client: httpx.AsyncClient | None = None
            client: AqualinkClient | None = None

            try:
                httpx_client = httpx.AsyncClient(
                    http2=True,
                    limits=httpx.Limits(keepalive_expiry=KEEPALIVE_EXPIRY),
                )
                client = AqualinkClient(username, password, httpx_client)
                await client.login()

            except Exception as e:
                _LOGGER.error("Failed to login: %s", e, exc_info=True)
                errors["base"] = "invalid_auth"

            finally:
                # On ferme explicitement : le config_flow ne doit pas garder un client ouvert
                if client is not None:
                    await client.close()
                elif httpx_client is not None:
                    await httpx_client.aclose()

            if not errors:
                return self.async_create_entry(
                    title=username,
                    data={CONF_USERNAME: username, CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_import(self, import_info: dict[str, Any]) -> FlowResult:
        """Handle import from configuration.yaml."""
        return await self.async_step_user(import_info)