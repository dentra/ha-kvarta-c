"""Config flow for integration."""

from __future__ import annotations
import logging
from collections.abc import Mapping
from typing import Any, Final, Dict
from datetime import timedelta

import aiohttp
import voluptuous as vol

from homeassistant.helpers import entity_registry as er, selector
from homeassistant import config_entries, exceptions
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, callback

from . import const, kvartac_api
from .coordinator import (
    KvartaCDataUpdateCoordinator,
    create_api,
    async_fetch,
    get_update_interval,
)
from .services import linked_preview

_LOGGER = logging.getLogger(__name__)

DEMO_ACC_ID: Final = "000000000"
DEMO_ORG_ID: Final = "0000"
DEMO_PASSWD: Final = "demo"

# счетчики, в которые передаются показания, как в фильтре services.yaml
_COUNTER_DEVICE_CLASSES: Final = (
    SensorDeviceClass.GAS,
    SensorDeviceClass.VOLUME,
    SensorDeviceClass.ENERGY,
)


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

    api = await async_check_login(hass, data)

    return {"title": api.account, "api": api}


async def async_check_login(hass: HomeAssistant, data: Mapping[str, Any]):
    """Login and fetch account data."""
    api = create_api(hass, data)

    try:
        await async_fetch(api)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise CannotConnect from err

    return api


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

    async def async_step_reauth(self, entry_data: Mapping[str, Any]):
        """Start reauth on wrong saved password."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """Ask for a new password."""
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            data = {**entry.data, const.CONF_PASSWD: user_input[const.CONF_PASSWD]}
            try:
                await async_check_login(self.hass, data)
                return self.async_update_reload_and_abort(entry, data=data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except kvartac_api.ApiAuthError:
                errors["base"] = "invalid_auth"
            except kvartac_api.ApiError:
                errors["base"] = "api_error"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(const.CONF_PASSWD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    ),
                }
            ),
            description_placeholders={
                "org_id": entry.data[const.CONF_ORG_ID],
                "acc_id": entry.data[const.CONF_ACC_ID],
            },
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle an options flow for integration."""

    _options: dict[str, Any]

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage options."""
        if user_input is not None:
            self._options = user_input
            if not self._counters():
                return await self.async_step_no_counters()
            return await self.async_step_links()

        # координатора нет, если запись не загрузилась
        coordinator: KvartaCDataUpdateCoordinator | None = self.hass.data.get(
            const.DOMAIN, {}
        ).get(self.config_entry.entry_id)
        update_interval = get_update_interval(self.config_entry.options)

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
                        default=timedelta_to_dict(update_interval),
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
                "acc_info": (
                    coordinator.api.account if coordinator else self.config_entry.title
                ),
                "org_info": coordinator.api.organisation if coordinator else "",
            },
        )

    async def async_step_no_counters(self, user_input: dict[str, Any] | None = None):
        """Explain why links can't be set up yet."""
        if user_input is None:
            # пустой include_entities разрешил бы выбрать любую сущность
            return self.async_show_form(step_id="no_counters")

        options = dict(self._options)
        if links := self.config_entry.options.get(const.CONF_LINKS):
            options[const.CONF_LINKS] = links
        return self.async_create_entry(title="", data=options)

    async def async_step_links(self, user_input: dict[str, Any] | None = None):
        """Manage linked source sensors."""
        errors = {}
        if user_input is not None:
            links = user_input.get(const.CONF_LINKS) or []
            counters = [link[ATTR_ENTITY_ID] for link in links]
            if len(counters) != len(set(counters)):
                errors["base"] = "duplicate_link"
            elif not set(counters) <= set(self._counters()):
                errors["base"] = "missing_meter"
            else:
                options = dict(self._options)
                if links:
                    options[const.CONF_LINKS] = links
                return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="links",
            data_schema=vol.Schema(
                {
                    # без default: иначе пустое поле вернет удаленные связи
                    optional(
                        const.CONF_LINKS,
                        user_input or dict(self.config_entry.options),
                        [],
                    ): self._links_selector(),
                }
            ),
            description_placeholders={
                "preview": linked_preview(self.hass, self.config_entry.entry_id)
            },
            errors=errors,
        )

    def _entities(self) -> list[er.RegistryEntry]:
        registry = er.async_get(self.hass)
        return [
            reg
            for entry in self.hass.config_entries.async_entries(const.DOMAIN)
            for reg in er.async_entries_for_config_entry(registry, entry.entry_id)
        ]

    def _counters(self) -> list[str]:
        registry = er.async_get(self.hass)
        return [
            reg.entity_id
            for reg in er.async_entries_for_config_entry(
                registry, self.config_entry.entry_id
            )
            if reg.domain == "sensor"
            and reg.original_device_class in _COUNTER_DEVICE_CLASSES
            # отключенному счетчику показания не передать
            and not reg.disabled
        ]

    def _links_selector(self) -> selector.ObjectSelector:
        # устаревшие счетчики связей должны пройти селектор, их отсекает проверка
        counters = list(
            dict.fromkeys(
                self._counters()
                + [
                    link[ATTR_ENTITY_ID]
                    for link in self.config_entry.options.get(const.CONF_LINKS, [])
                ]
            )
        )
        return selector.ObjectSelector(
            selector.ObjectSelectorConfig(
                multiple=True,
                label_field=ATTR_ENTITY_ID,
                description_field=const.CONF_SOURCE,
                translation_key=const.CONF_LINKS,
                fields={
                    ATTR_ENTITY_ID: {
                        "required": True,
                        "selector": selector.EntitySelector(
                            selector.EntitySelectorConfig(include_entities=counters)
                        ),
                    },
                    const.CONF_SOURCE: {
                        "required": True,
                        "selector": selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain=["sensor", "input_number"],
                                exclude_entities=[
                                    reg.entity_id for reg in self._entities()
                                ],
                            )
                        ),
                    },
                },
            )
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAccId(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid account id."""


class InvalidOrgId(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid organisation id."""
