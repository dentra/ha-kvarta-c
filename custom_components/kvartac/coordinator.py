"""Kvarta-C data update coordinator."""

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Final, Protocol

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACC_ID,
    CONF_ORG_ID,
    CONF_PASSWD,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MESSAGE_SUCCESS,
    ErrorCode,
    make_result,
)
from .kvartac_api import ApiAuthError, ApiError, KvartaCApi

_LOGGER = logging.getLogger(__name__)

API_TIMEOUT: Final = 10


def get_update_interval(options: Mapping[str, Any]) -> timedelta:
    """Return update interval from config entry options."""
    return cv.time_period(
        options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL.total_seconds())
    )


def create_api(
    hass: HomeAssistant,
    data: Mapping[str, Any],
    session: aiohttp.ClientSession | None = None,
) -> KvartaCApi:
    """Create api from config entry data."""
    return KvartaCApi(
        session or async_get_clientsession(hass),
        data[CONF_ORG_ID],
        data[CONF_ACC_ID],
        data[CONF_PASSWD],
    )


async def async_fetch(api: KvartaCApi) -> None:
    """Login and fetch new data with timeout."""
    async with asyncio.timeout(API_TIMEOUT):
        await api.async_fetch()


class CounterEntity(Protocol):
    """Counter sensor readings are sent to."""

    entity_id: str
    counter_id: str

    def check_value(self, value: int) -> dict | None:
        """Return a service response error if the value can't be sent."""


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
        # своя сессия: вход другого счета в общей сессии заменит cookie
        # между входом и отправкой показаний
        self._session = async_create_clientsession(hass)
        self.api = create_api(hass, entry.data, self._session)
        # запросы к сайту не должны пересекаться: другой вход в той же
        # сессии может попасть между входом и отправкой показаний
        self._lock = asyncio.Lock()

    async def async_send_values(
        self, readings: list[tuple[CounterEntity, int]]
    ) -> list[dict]:
        """Check and send readings in one request, errors are returned as results.

        Counters failed the check are skipped, others are still sent.
        """
        async with self._lock:
            results = []
            values: dict[str, int] = {}
            entity_ids = []
            for entity, value in readings:
                if error := entity.check_value(value):
                    results.append({"entity_ids": [entity.entity_id]} | error)
                else:
                    values[entity.counter_id] = value
                    entity_ids.append(entity.entity_id)
            if values:
                response = await self._async_send(values)
                results.append({"entity_ids": entity_ids} | response)
            return results

    async def _async_send(self, values: dict[str, int]) -> dict:
        _LOGGER.debug("Updating %s", values)
        try:
            async with asyncio.timeout(API_TIMEOUT):
                await self.api.async_update(values)
        except ApiAuthError:
            # из сервиса reauth сам не стартует
            self.config_entry.async_start_reauth(self.hass)
            return make_result(ErrorCode.AUTH, "Ошибка аутентификации")
        except ApiError as err:
            msg = f"Ошибка API: {err}" if str(err) else "Ошибка API"
            return make_result(ErrorCode.API, msg)
        except (aiohttp.ClientError, TimeoutError) as err:
            return make_result(ErrorCode.CONNECTION, f"Ошибка соединения: {err!r}")

        try:
            async with asyncio.timeout(API_TIMEOUT):
                await self.api.async_refetch()
        except ApiAuthError:
            # вход и отправка проверяют только статус ответа, без входа
            # сайт молча отбрасывает показания
            self.config_entry.async_start_reauth(self.hass)
            return make_result(ErrorCode.AUTH, "Ошибка аутентификации")
        except (ApiError, aiohttp.ClientError, TimeoutError) as err:
            # показания уже переданы, данные перечитаются после отправки
            _LOGGER.warning("Не удалось перечитать показания: %r", err)
            self.hass.async_create_task(self.async_request_refresh())
        else:
            self.async_set_updated_data(True)
        return make_result(ErrorCode.SUCCESS, MESSAGE_SUCCESS, payload=values)

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            # asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with self._lock:
                await async_fetch(self.api)
            return True
        except ApiAuthError as err:
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            raise ConfigEntryAuthFailed from err
        except ApiError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
