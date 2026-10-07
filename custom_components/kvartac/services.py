"""Service actions"""

import logging
from typing import Final

import voluptuous as vol
from homeassistant.components import sensor
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform

from . import const
from .coordinator import KvartaCDataUpdateCoordinator
from .sensor import MAX_VALUE, KvartaCCounterSensor

_LOGGER = logging.getLogger(__name__)

_VALUE: Final = "value"
_VALUES: Final = "values"

_SCHEMA_VALUE = vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_VALUE))
_THROWS = {vol.Optional("throws", default=True): cv.boolean}

_UPDATE_VALUE_SCHEMA = vol.All(
    vol.Schema(
        {
            **cv.ENTITY_SERVICE_FIELDS,
            vol.Exclusive(_VALUE, _VALUE): _SCHEMA_VALUE,
            vol.Exclusive(_VALUES, _VALUE): vol.All(
                cv.ensure_list,
                [
                    vol.Schema(
                        {
                            vol.Required(ATTR_ENTITY_ID): cv.entity_id,
                            vol.Required(_VALUE): _SCHEMA_VALUE,
                        }
                    )
                ],
            ),
            **_THROWS,
        }
    ),
    cv.has_at_least_one_key(_VALUE, _VALUES),
)

_TARGET_KEYS = {str(key) for key in cv.ENTITY_SERVICE_FIELDS}

type _Readings = list[tuple[KvartaCCounterSensor, int]]


def async_setup_services(hass: HomeAssistant) -> None:
    """Register service actions."""

    async def async_execute_update_value(service_call: ServiceCall) -> ServiceResponse:
        if _VALUES in service_call.data:
            readings = _values_readings(hass, service_call)
        else:
            readings = await _target_readings(hass, service_call)
        results = await _async_send(readings)
        return _response(results, service_call)

    hass.services.async_register(
        const.DOMAIN,
        const.SERVICE_UPDATE_VALUE_CODE,
        async_execute_update_value,
        _UPDATE_VALUE_SCHEMA,
        SupportsResponse.OPTIONAL,
    )


def _response(results: list[dict], service_call: ServiceCall) -> ServiceResponse:
    failed = failed_results(results)
    throws = service_call.data["throws"]
    for result in failed if not throws else []:
        _LOGGER.warning("Показания не переданы: %s", result["message"])
    if failed and throws and not service_call.return_response:
        raise HomeAssistantError(failure_message(failed))
    if not service_call.return_response:
        return None
    return {
        "code": failed[0]["code"] if failed else 0,
        "message": failed[0]["message"] if failed else const.MESSAGE_SUCCESS,
        "results": results,
    }


def failed_results(results: list[dict]) -> list[dict]:
    """Return results with errors."""
    return [result for result in results if result["code"] != 0]


def failure_message(failed: list[dict]) -> str:
    """Join error messages of failed results."""
    return "; ".join(result["message"] for result in failed)


def _values_readings(hass: HomeAssistant, service_call: ServiceCall) -> _Readings:
    if _TARGET_KEYS & service_call.data.keys():
        raise ServiceValidationError("Цели задаются в values, а не в target")

    sensors = _counter_sensors(hass)
    readings: _Readings = []
    for item in service_call.data[_VALUES]:
        entity = sensors.get(item[ATTR_ENTITY_ID])
        if entity is None:
            raise ServiceValidationError(
                f"{item[ATTR_ENTITY_ID]} не является сенсором показаний"
            )
        if any(entity is other for other, _ in readings):
            raise ServiceValidationError(f"{entity.entity_id} указан несколько раз")
        readings.append((entity, item[_VALUE]))
    return readings


async def _target_readings(hass: HomeAssistant, service_call: ServiceCall) -> _Readings:
    entities = [
        entity
        for platform in entity_platform.async_get_platforms(hass, const.DOMAIN)
        if platform.domain == sensor.DOMAIN
        for entity in await platform.async_extract_from_service(service_call)
    ]
    if not entities:
        raise ServiceValidationError("Ни одной цели не выбрано")
    for entity in entities:
        if not isinstance(entity, KvartaCCounterSensor):
            raise ServiceValidationError("Цель должна быть сенсором показаний")
    return [(entity, service_call.data[_VALUE]) for entity in entities]


async def _async_send(readings: _Readings) -> list[dict]:
    """Send readings grouped by config entry, one request per entry."""
    groups: dict[KvartaCDataUpdateCoordinator, _Readings] = {}
    for entity, value in readings:
        groups.setdefault(entity.coordinator, []).append((entity, value))

    results = []
    for coordinator, group in groups.items():
        results += await coordinator.async_send_values(group)
    return results


def _counter_sensors(hass: HomeAssistant) -> dict[str, KvartaCCounterSensor]:
    return {
        entity.entity_id: entity
        for platform in entity_platform.async_get_platforms(hass, const.DOMAIN)
        if platform.domain == sensor.DOMAIN
        for entity in platform.entities.values()
        if isinstance(entity, KvartaCCounterSensor)
    }
