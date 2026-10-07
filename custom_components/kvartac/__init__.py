"""kvartac integration."""

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import config_validation as cv

from .kvartac_api import KvartaCApi, ApiError, ApiAuthError
from .const import (
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    CONF_ACC_ID,
    CONF_ORG_ID,
    CONF_PASSWD,
    DEFAULT_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


PLATFORMS: Final = ["sensor"]

API_TIMEOUT: Final = 10


def get_update_interval(options: Mapping[str, Any]) -> timedelta:
    """Return update interval from config entry options."""
    return cv.time_period(
        options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL.total_seconds())
    )


def create_api(hass: HomeAssistant, data: Mapping[str, Any]) -> KvartaCApi:
    """Create api from config entry data."""
    return KvartaCApi(
        async_get_clientsession(hass),
        data[CONF_ORG_ID],
        data[CONF_ACC_ID],
        data[CONF_PASSWD],
    )


async def async_fetch(api: KvartaCApi) -> None:
    """Login and fetch new data with timeout."""
    async with asyncio.timeout(API_TIMEOUT):
        await api.async_fetch()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""

    _LOGGER.debug(
        "Setup %s (%s %s)",
        entry.title,
        entry.data[CONF_ORG_ID],
        entry.data[CONF_ACC_ID],
    )

    hass.data.setdefault(DOMAIN, {})

    coordinator = KvartaCDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


# https://developers.home-assistant.io/docs/integration_fetching_data/#polling-api-endpoints
class KvartaCDataUpdateCoordinator(DataUpdateCoordinator):
    """Kvarta-C data update coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=get_update_interval(entry.options),
        )
        _LOGGER.debug("Update interval is %s", self.update_interval)
        self.api = create_api(hass, entry.data)

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            # asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            await async_fetch(self.api)
            return True
        except ApiAuthError as err:
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            raise ConfigEntryAuthFailed from err
        except ApiError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
