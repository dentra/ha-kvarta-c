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
    HASS_API,
    DOMAIN,
    CONF_ACC_ID,
    CONF_ORG_ID,
    CONF_PASSWD,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


PLATFORMS: Final = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api: KvartaCApi = None
    if HASS_API in hass.data[DOMAIN]:
        api = hass.data[DOMAIN][HASS_API]
        if (
            api.organisation_id != entry.data[CONF_ORG_ID]
            or api.account_id != entry.data[CONF_ACC_ID]
        ):
            api = None

    if not api:
        api = KvartaCApi(
            async_get_clientsession(hass),
            entry.data[CONF_ORG_ID],
            entry.data[CONF_ACC_ID],
            entry.data[CONF_PASSWD],
        )
        await api.async_fetch()

    coordinator = KvartaCDataUpdateCoordinator(hass, api)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # add options handler
    if not entry.update_listeners:
        entry.add_update_listener(async_update_options)

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

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

    def __init__(self, hass: HomeAssistant, api: KvartaCApi):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.api = api

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            # asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(10):
                return await self.api.async_fetch()
        except ApiAuthError as err:
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            raise ConfigEntryAuthFailed from err
        except ApiError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
