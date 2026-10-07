"""Kvarta-C data update coordinator."""

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACC_ID,
    CONF_ORG_ID,
    CONF_PASSWD,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .kvartac_api import ApiAuthError, ApiError, KvartaCApi

_LOGGER = logging.getLogger(__name__)

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
