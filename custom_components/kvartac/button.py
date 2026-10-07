"""Button implementation routines"""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import const
from .coordinator import KvartaCDataUpdateCoordinator
from .kvartac_api import KvartaCApi
from .sensor import device_info
from .services import async_send_linked, failed_results, failure_message


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the platform from config entry."""
    coordinator: KvartaCDataUpdateCoordinator = hass.data[const.DOMAIN][entry.entry_id]

    if entry.options.get(const.CONF_LINKS):
        async_add_entities([KvartaCSendLinkedButton(coordinator.api, entry.entry_id)])
        return

    # связей больше нет, убираем кнопку из реестра
    registry = er.async_get(hass)
    unique_id = KvartaCSendLinkedButton.make_unique_id(coordinator.api)
    if entity_id := registry.async_get_entity_id("button", const.DOMAIN, unique_id):
        registry.async_remove(entity_id)


class KvartaCSendLinkedButton(ButtonEntity):
    """Send readings of linked source sensors."""

    _attr_has_entity_name = True
    _attr_translation_key = const.SERVICE_SEND_LINKED
    _attr_icon = "mdi:send"

    def __init__(self, api: KvartaCApi, entry_id: str) -> None:
        self._entry_id = entry_id
        self._attr_unique_id = self.make_unique_id(api)
        self._attr_device_info = device_info(api, entry_id)

    @staticmethod
    def make_unique_id(api: KvartaCApi) -> str:
        """Return unique id of the button."""
        return f"{const.DOMAIN}.{api.uid}_{const.SERVICE_SEND_LINKED}"

    async def async_press(self) -> None:
        results = await async_send_linked(self.hass, self._entry_id)
        if failed := failed_results(results):
            raise HomeAssistantError(failure_message(failed))
