"""Sensor implementaion routines"""
import logging
from typing import Any, Callable, Final
from datetime import datetime, date, timedelta

import voluptuous as vol

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceEntryType

from homeassistant.const import (
    VOLUME_CUBIC_METERS,
    ENERGY_KILO_WATT_HOUR,
)

from .const import CONF_DIAGNOSTIC_SENSORS, CONF_UPDATE_INTERVAL, DOMAIN

from .kvartac_api import KvartaCApi
from . import KvartaCDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


SENSOR_ELECTRICITY: Final = SensorEntityDescription(
    key="electricity",
    native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
    device_class=SensorDeviceClass.ENERGY,
    state_class=SensorStateClass.TOTAL_INCREASING,
)

SENSOR_GAS: Final = SensorEntityDescription(
    key="gas",
    native_unit_of_measurement=VOLUME_CUBIC_METERS,
    device_class=SensorDeviceClass.GAS,
    state_class=SensorStateClass.TOTAL_INCREASING,
)

SENSOR_WATER_HOT: Final = SensorEntityDescription(
    key="water_hot",
    icon="mdi:water",
    native_unit_of_measurement=VOLUME_CUBIC_METERS,
    state_class=SensorStateClass.TOTAL_INCREASING,
)

SENSOR_WATER_COLD: Final = SensorEntityDescription(
    key="water_cold",
    icon="mdi:water-outline",
    native_unit_of_measurement=VOLUME_CUBIC_METERS,
    state_class=SensorStateClass.TOTAL_INCREASING,
)

SENSOR_SAVE_DATE: Final = SensorEntityDescription(
    key="save_date",
    entity_registry_enabled_default=True,
    icon="mdi:calendar-sync",
    device_class=SensorDeviceClass.DATE,
    # state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Callable
):
    """Set up the platform from config entry."""

    coordinator: KvartaCDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    if CONF_UPDATE_INTERVAL in entry.options:
        coordinator.update_interval = timedelta(
            seconds=entry.options[CONF_UPDATE_INTERVAL]
        )

    async_add_entities(
        KvartaCCounterSensor(
            coordinator,
            entry.entry_id,
            counter,
            entry.options.get(CONF_DIAGNOSTIC_SENSORS, False),
        )
        for counter in coordinator.api.counters.keys()
    )
    async_add_entities([KvartaCDiagnosticSensor(coordinator, entry.entry_id)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "update_value",
        {
            vol.Required("value"): vol.All(
                vol.Coerce(int),
                vol.Range(min=1),
            ),
        },
        _KvartaCSensor.async_update_value.__name__,
    )


class _KvartaCSensor(CoordinatorEntity[KvartaCDataUpdateCoordinator], SensorEntity):
    def __init__(self, coordinator: KvartaCDataUpdateCoordinator, entry_id: str):
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry_id)},
            configuration_url=KvartaCApi.BASE_URL,
            name=self.coordinator.api.account,
            model=self.coordinator.api.account,
            manufacturer=self.coordinator.api.organisation,
        )

    @property
    def _api(self) -> KvartaCApi:
        return self.coordinator.api

    async def async_update_value(self, value: int):
        """nothing to do with RO valaue"""


class KvartaCDiagnosticSensor(_KvartaCSensor):
    """Respresent prev save date sensor."""

    def __init__(self, coordinator: KvartaCDataUpdateCoordinator, entry_id: str):
        super().__init__(coordinator, entry_id)
        self._attr_extra_state_attributes = {
            "account": self._api.account,
            "account_id": self._api.account_id,
            "organisation": self._api.organisation,
            "organisation_id": self._api.organisation_id,
        }
        self._attr_name = f"Предыдущие показания {self._api.account}"
        uid = f"{self._api.uid}_date"
        self._attr_unique_id = f"kvartac.{uid}"
        self.entity_id = f"sensor.{uid}"
        self.entity_description = SENSOR_SAVE_DATE

    @property
    def native_value(self) -> date:
        """Return the value of the sensor."""
        return datetime.strptime(self._api.prev_save_date, "%d.%m.%Y").date()


class KvartaCCounterSensor(_KvartaCSensor):
    """Respresent value-counter sensor."""

    def __init__(
        self,
        coordinator: KvartaCDataUpdateCoordinator,
        entry_id: str,
        counter_id: str,
        diag_sensors: bool,
    ):
        super().__init__(coordinator, entry_id)
        self._counter_id = counter_id

        counter = self._counter
        service = counter[KvartaCApi.COUNTER_SERVICE]

        self._attr_extra_state_attributes = {
            "service": service,
            "counter": counter[KvartaCApi.COUNTER_ID],
        }
        self._attr_name = f"{service} {counter[KvartaCApi.COUNTER_ID]}"
        uid = f"{self._api.uid}_{counter_id}_value"
        self._attr_unique_id = f"{DOMAIN}.{uid}"
        self.entity_id = f"sensor.{uid}"

        if service.lower().endswith("энергия"):
            self.entity_description = SENSOR_ELECTRICITY
        elif service.lower().startswith("газ"):
            self.entity_description = SENSOR_GAS
        elif service.lower().startswith("гор"):
            self.entity_description = SENSOR_WATER_HOT
        else:
            self.entity_description = SENSOR_WATER_COLD

        if diag_sensors:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def _counter(self) -> dict[str, Any]:
        return self._api.counters[self._counter_id]

    @property
    def native_value(self) -> int:
        """Return the value of the sensor."""
        return self._counter[KvartaCApi.COUNTER_VALUE]

    def __str__(self):
        return f"{self._counter}"

    async def async_update_value(self, value: int):
        if value < self.state:
            _LOGGER.error("[%s] New value is less than passes %d", self.name, value)
        elif value == self.state:
            pass
        else:
            _LOGGER.debug("[%s]: Updating to %d", self.name, value)
            await self._api.async_update(self._counter_id, value)

        self.async_write_ha_state()
        # await self.coordinator.async_request_refresh()
