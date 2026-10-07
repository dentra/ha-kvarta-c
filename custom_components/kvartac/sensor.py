"""Sensor implementaion routines"""

import logging
import math
from typing import Any, Callable, Final
from datetime import date

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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType

from homeassistant.const import UnitOfVolume, UnitOfEnergy

from .kvartac_api import KvartaCApi
from . import const
from .const import ErrorCode, make_result
from .coordinator import KvartaCDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


MAX_VALUE: Final = 999999

SENSOR_ELECTRICITY: Final = SensorEntityDescription(
    key="electricity",
    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    device_class=SensorDeviceClass.ENERGY,
    state_class=SensorStateClass.TOTAL_INCREASING,
)

SENSOR_GAS: Final = SensorEntityDescription(
    key="gas",
    native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
    device_class=SensorDeviceClass.GAS,
    state_class=SensorStateClass.TOTAL_INCREASING,
)

SENSOR_WATER_HOT: Final = SensorEntityDescription(
    key="water_hot",
    icon="mdi:water",
    device_class=SensorDeviceClass.VOLUME,
    native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
    state_class=SensorStateClass.TOTAL_INCREASING,
)

SENSOR_WATER_COLD: Final = SensorEntityDescription(
    key="water_cold",
    icon="mdi:water-outline",
    device_class=SensorDeviceClass.VOLUME,
    native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
    state_class=SensorStateClass.TOTAL_INCREASING,
)

SENSOR_HEATING: Final = SensorEntityDescription(
    key="heating",
    icon="mdi:radiator",
    device_class=SensorDeviceClass.ENERGY,
    native_unit_of_measurement=UnitOfEnergy.GIGA_CALORIE,
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


def device_info(api: KvartaCApi, entry_id: str) -> DeviceInfo:
    """Return device info of the config entry."""
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(const.DOMAIN, entry_id)},
        configuration_url=KvartaCApi.BASE_URL,
        name=api.account,
        model=api.account,
        manufacturer=api.organisation,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Callable
):
    """Set up the platform from config entry."""

    coordinator: KvartaCDataUpdateCoordinator = hass.data[const.DOMAIN][entry.entry_id]

    diag = entry.options.get(const.CONF_DIAGNOSTIC_SENSORS, False)
    async_add_entities(
        KvartaCCounterSensor(coordinator, entry.entry_id, counter, diag)
        for counter in coordinator.api.counters.keys()
    )

    if entry.options.get(const.CONF_PREV_DATE_SENSOR, True):
        async_add_entities([KvartaCDiagnosticSensor(coordinator, entry.entry_id)])
    else:
        # сенсор выключен в настройках, убираем его из реестра
        registry = er.async_get(hass)
        unique_id = KvartaCDiagnosticSensor.make_unique_id(coordinator.api)
        if entity_id := registry.async_get_entity_id("sensor", const.DOMAIN, unique_id):
            registry.async_remove(entity_id)


class _KvartaCSensor(CoordinatorEntity[KvartaCDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: KvartaCDataUpdateCoordinator, entry_id: str):
        super().__init__(coordinator)
        self._attr_device_info = device_info(coordinator.api, entry_id)

    @property
    def _api(self) -> KvartaCApi:
        return self.coordinator.api


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
        self._attr_name = "Предыдущие показания"
        self._attr_unique_id = self.make_unique_id(self._api)
        self.entity_id = f"sensor.{self._api.uid}_date"
        self.entity_description = SENSOR_SAVE_DATE

    @staticmethod
    def make_unique_id(api: KvartaCApi) -> str:
        """Return unique id of the sensor."""
        return f"{const.DOMAIN}.{api.uid}_date"

    @property
    def native_value(self) -> date:
        """Return the value of the sensor."""
        return self._api.prev_save_date


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

        uid = f"{self._api.uid}_{counter_id}"
        self.entity_id = f"sensor.{uid}"

        self._attr_unique_id = f"{const.DOMAIN}.{uid}"
        self._attr_name = f"{service} {counter[KvartaCApi.COUNTER_ID]}"

        service = service.lower()
        if service.startswith("отопл") or service.startswith("тепл"):
            self.entity_description = SENSOR_HEATING
        elif "энерг" in service or "электр" in service:
            self.entity_description = SENSOR_ELECTRICITY
        elif service.startswith("газ"):
            self.entity_description = SENSOR_GAS
        elif service.startswith("гор") or service.startswith("гвс"):
            self.entity_description = SENSOR_WATER_HOT
        else:
            self.entity_description = SENSOR_WATER_COLD

        if diag_sensors:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def counter_id(self) -> str:
        """Return counter id of the site form."""
        return self._counter_id

    @property
    def _counter(self) -> dict[str, Any] | None:
        # счетчик может пропасть из ответа, если его не удалось распарсить
        return self._api.counters.get(self._counter_id)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._counter is not None

    @property
    def native_value(self) -> int | float | None:
        """Return the value of the sensor."""
        counter = self._counter
        return counter[KvartaCApi.COUNTER_VALUE] if counter else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        counter = self._counter
        if counter is None:
            return None
        prev_save_date = self._api.prev_save_date
        return {
            "service": counter[KvartaCApi.COUNTER_SERVICE],
            "counter": counter[KvartaCApi.COUNTER_ID],
            "counter_id": self._counter_id,
            "date": prev_save_date.isoformat() if prev_save_date else None,
            "account": self._api.account,
            "account_id": self._api.account_id,
            "organisation": self._api.organisation,
            "organisation_id": self._api.organisation_id,
        }

    def __str__(self):
        return f"{self._counter}"

    def check_value(self, value: int) -> dict | None:
        """Return a service response error if the value can't be sent."""
        if not self.available:
            msg = f"Счетчик {self._counter_id} недоступен"
            return make_result(ErrorCode.UNAVAILABLE, msg)
        # неизменившиеся показания можно передать повторно, передаются
        # только целые, поэтому дробная часть прежних не учитывается
        if value < math.floor(self.native_value):
            msg = f"Новое значение {value} меньше предыдущего {self.state}"
            return make_result(ErrorCode.VALUE, msg)
        if value > MAX_VALUE:
            msg = f"Новое значение {value} больше {MAX_VALUE}"
            return make_result(ErrorCode.VALUE, msg)
        return None
