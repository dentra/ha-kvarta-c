"""kvartac integration."""

import logging
from typing import Final

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONF_ACC_ID, CONF_ORG_ID
from .coordinator import KvartaCDataUpdateCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


PLATFORMS: Final = ["sensor", "button"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""
    async_setup_services(hass)
    return True


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
    # сессия закрывается и при неудачной настройке
    entry.async_on_unload(coordinator.async_close)
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
