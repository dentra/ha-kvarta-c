"""Config flow for integration."""
from __future__ import annotations
import logging
from typing import Any, Final

import voluptuous as vol

from homeassistant.helpers import config_validation as cv
from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .kvartac_api import KvartaCApi, ApiAuthError, ApiError

from .const import (
    DOMAIN,
    CONF_ACC_ID,
    CONF_ORG_ID,
    CONF_PASSWD,
    CONF_UPDATE_INTERVAL,
    CONF_DIAGNOSTIC_SENSORS,
    HASS_API,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

DEMO_ACC_ID: Final = "000000000"
DEMO_ORG_ID: Final = "0000"
DEMO_PASSWD: Final = "demo"


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect."""

    if len(data[CONF_ORG_ID]) != 4:
        raise InvalidOrgId

    if len(data[CONF_ACC_ID]) == 0:
        raise InvalidAccId

    if (
        data[CONF_ORG_ID] == DEMO_ORG_ID
        or data[CONF_ACC_ID] == DEMO_ACC_ID
        or data[CONF_PASSWD] == DEMO_PASSWD
    ):
        data[CONF_ORG_ID] = DEMO_ORG_ID
        data[CONF_ACC_ID] = DEMO_ACC_ID
        data[CONF_PASSWD] = DEMO_PASSWD

    api = KvartaCApi(
        async_get_clientsession(hass),
        data[CONF_ORG_ID],
        data[CONF_ACC_ID],
        data[CONF_PASSWD],
    )

    await api.async_fetch()

    return {"title": api.account, "api": api}


class ConfigFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for integration."""

    VERSION = 1

    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                api: KvartaCApi = info["api"]
                await self.async_set_unique_id(f"{DOMAIN}_{api.uid}")
                self._abort_if_unique_id_configured()

                self.hass.data.setdefault(DOMAIN, {})[HASS_API] = api

                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAccId:
                errors["base"] = "invalid_acc_id"
            except InvalidOrgId:
                errors["base"] = "invalid_org_id"
            except ApiAuthError:
                errors["base"] = "invalid_auth"
            except ApiError:
                errors["base"] = "api_error"
        else:
            user_input = {
                CONF_ORG_ID: "",
                CONF_ACC_ID: "",
                CONF_PASSWD: "",
            }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ORG_ID, default=user_input.get(CONF_ORG_ID, "")
                    ): cv.string,
                    vol.Required(
                        CONF_ACC_ID, default=user_input.get(CONF_ACC_ID, "")
                    ): cv.string,
                    vol.Optional(
                        CONF_PASSWD, default=user_input.get(CONF_PASSWD, "")
                    ): cv.string,
                },
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        # self.entry = entry
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        api: KvartaCApi = self.hass.data[DOMAIN][self.config_entry.entry_id].api

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, UPDATE_INTERVAL.total_seconds
                        ),
                    ): cv.positive_int,
                    vol.Required(
                        CONF_DIAGNOSTIC_SENSORS,
                        default=self.config_entry.options.get(
                            CONF_DIAGNOSTIC_SENSORS, True
                        ),
                    ): cv.boolean,
                }
            ),
            description_placeholders={
                "acc_info": api.account,
                "org_info": api.organisation,
            },
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAccId(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid account id."""


class InvalidOrgId(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid organisation id."""
