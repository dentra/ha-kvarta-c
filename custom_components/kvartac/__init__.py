"""kvartac integration."""
import logging

from typing import Final
import async_timeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import (
    config_validation as cv,
    entity_platform,
    service,
    entity_registry,
    device_registry,
)
from homeassistant.helpers.typing import UNDEFINED
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

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
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()

    # add options handler
    if not entry.update_listeners:
        entry.add_update_listener(async_update_options)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    """Update from a config entry options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data[DOMAIN].pop(entry.entry_id)

    # workaround to reset diagnostic entity_category
    registry = entity_registry.async_get(hass)
    entities = entity_registry.async_entries_for_config_entry(registry, entry.entry_id)
    for entity in entities:
        if entity.entity_id.endswith("_value"):
            registry.async_update_entity(entity.entity_id, entity_category=None)

    return unload_ok


# https://developers.home-assistant.io/docs/integration_fetching_data/#polling-api-endpoints
class KvartaCDataUpdateCoordinator(DataUpdateCoordinator):
    """Kvarta-C data update coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=cv.time_period(
                entry.options.get(
                    CONF_UPDATE_INTERVAL,
                    DEFAULT_UPDATE_INTERVAL.total_seconds(),
                )
            ),
        )
        _LOGGER.debug("Update interval is %s", self.update_interval)
        self.api = KvartaCApi(
            async_get_clientsession(hass),
            entry.data[CONF_ORG_ID],
            entry.data[CONF_ACC_ID],
            entry.data[CONF_PASSWD],
        )

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            # asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(10):
                await self.api.async_fetch()
                return True
        except ApiAuthError as err:
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            raise ConfigEntryAuthFailed from err
        except ApiError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
