"""Config flow for integration."""
from __future__ import annotations
import logging
from typing import Any, Final, Dict
from datetime import timedelta

import voluptuous as vol

from homeassistant.helpers import selector
from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import const, kvartac_api, KvartaCDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

DEMO_ACC_ID: Final = "000000000"
DEMO_ORG_ID: Final = "0000"
DEMO_PASSWD: Final = "demo"


def _marker(
    marker: vol.Marker, key: str, options: Dict[str, Any], default: Any | None = None
):
    if default is None:
        return marker(key)

    if isinstance(options, dict) and key in options:
        suggested_value = options[key]
    else:
        suggested_value = default

    return marker(key, description={"suggested_value": suggested_value})


def required(
    key: str, options: Dict[str, Any], default: Any | None = None
) -> vol.Required:
    """Return vol.Required."""
    return _marker(vol.Required, key, options, default)


def optional(
    key: str, options: Dict[str, Any], default: Any | None = None
) -> vol.Optional:
    """Return vol.Required."""
    return _marker(vol.Optional, key, options, default)


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect."""

    if len(data[const.CONF_ORG_ID]) != 4:
        raise InvalidOrgId

    if len(data[const.CONF_ACC_ID]) == 0:
        raise InvalidAccId

    # check for demo account
    if (
        data[const.CONF_ORG_ID] == DEMO_ORG_ID
        or data[const.CONF_ACC_ID] == DEMO_ACC_ID
        or data[const.CONF_PASSWD] == DEMO_PASSWD
    ):
        data[const.CONF_ORG_ID] = DEMO_ORG_ID
        data[const.CONF_ACC_ID] = DEMO_ACC_ID
        data[const.CONF_PASSWD] = DEMO_PASSWD

    api = kvartac_api.KvartaCApi(
        async_get_clientsession(hass),
        data[const.CONF_ORG_ID],
        data[const.CONF_ACC_ID],
        data[const.CONF_PASSWD],
    )

    await api.async_fetch()

    return {"title": api.account, "api": api}


class ConfigFlowHandler(config_entries.ConfigFlow, domain=const.DOMAIN):
    """Handle a config flow for integration."""

    VERSION = 1

    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                api: kvartac_api.KvartaCApi = info["api"]
                await self.async_set_unique_id(f"{const.DOMAIN}_{api.uid}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAccId:
                errors["base"] = "invalid_acc_id"
            except InvalidOrgId:
                errors["base"] = "invalid_org_id"
            except kvartac_api.ApiAuthError:
                errors["base"] = "invalid_auth"
            except kvartac_api.ApiError:
                errors["base"] = "api_error"
        else:
            user_input = {
                const.CONF_ORG_ID: "",
                const.CONF_ACC_ID: "",
                const.CONF_PASSWD: "",
            }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    required(const.CONF_ORG_ID, user_input): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT
                        ),
                    ),
                    required(const.CONF_ACC_ID, user_input): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT
                        ),
                    ),
                    required(const.CONF_PASSWD, user_input): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    ),
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

        coordinator: KvartaCDataUpdateCoordinator = self.hass.data[const.DOMAIN][
            self.config_entry.entry_id
        ]

        def timedelta_to_dict(delta: timedelta) -> dict:
            hours, seconds = divmod(delta.seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            return {
                "days": delta.days,
                "hours": hours,
                "minutes": minutes,
                "seconds": seconds,
            }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        const.CONF_UPDATE_INTERVAL,
                        default=timedelta_to_dict(coordinator.update_interval),
                    ): selector.DurationSelector(
                        selector.DurationSelectorConfig(enable_day=True),
                    ),
                    vol.Optional(
                        const.CONF_PREV_DATE_SENSOR,
                        default=self.config_entry.options.get(
                            const.CONF_PREV_DATE_SENSOR, True
                        ),
                    ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
                    vol.Optional(
                        const.CONF_DIAGNOSTIC_SENSORS,
                        default=self.config_entry.options.get(
                            const.CONF_DIAGNOSTIC_SENSORS, False
                        ),
                    ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
                }
            ),
            description_placeholders={
                "acc_info": coordinator.api.account,
                "org_info": coordinator.api.organisation,
            },
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAccId(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid account id."""


class InvalidOrgId(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid organisation id."""
