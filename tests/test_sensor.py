import pytest
from homeassistant.const import STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.kvartac import const

from .conftest import LOGIN_URL, TENANT_URL, UID, calls, load_fixture, mock_site

COLD = f"sensor.{UID}_service1counter1"
HEATING = f"sensor.{UID}_service3counter1"
HOT = f"sensor.{UID}_service5counter1"
DATE = f"sensor.{UID}_date"


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_site(aioclient_mock)
    if config_entry.entry_id not in hass.config_entries.async_entry_ids():
        config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_counter_sensors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry)

    cold = hass.states.get(COLD)
    assert cold.attributes["friendly_name"] == "Невский пр. д.1, кв. 13 ХВС, 1 33334566"
    assert cold.state == "161"
    assert cold.attributes["device_class"] == "volume"
    assert cold.attributes["unit_of_measurement"] == "m³"
    assert cold.attributes["icon"] == "mdi:water-outline"
    assert cold.attributes["counter"] == "33334566"
    assert cold.attributes["date"] == "2023-03-25"
    assert cold.attributes["organisation"] == 'ТСЖ "Колизей"'

    assert hass.states.get(HOT).attributes["icon"] == "mdi:water"

    heating = hass.states.get(HEATING)
    assert heating.state == "18.9033"
    assert heating.attributes["device_class"] == "energy"
    assert heating.attributes["unit_of_measurement"] == "Gcal"

    date = hass.states.get(DATE)
    assert date.state == "2023-03-25"
    assert date.attributes["friendly_name"] == (
        "Невский пр. д.1, кв. 13 Предыдущие показания"
    )
    assert len(hass.states.async_entity_ids("sensor")) == 6


async def test_sensor_options(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            const.CONF_PREV_DATE_SENSOR: False,
            const.CONF_DIAGNOSTIC_SENSORS: True,
        },
    )
    await _setup(hass, aioclient_mock, config_entry)

    assert hass.states.get(DATE) is None
    entity = er.async_get(hass).async_get(COLD)
    assert entity.entity_category is EntityCategory.DIAGNOSTIC

    # после выключения опции категория сбрасывается
    hass.config_entries.async_update_entry(
        config_entry, options={const.CONF_DIAGNOSTIC_SENSORS: False}
    )
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(COLD).entity_category is None
    assert hass.states.get(DATE) is not None


async def test_counter_missing(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry)

    tenant = load_fixture("tenant.html").replace('name="service1counter1"', "")
    aioclient_mock.clear_requests()
    aioclient_mock.post(LOGIN_URL, text="")
    aioclient_mock.get(TENANT_URL, text=tenant)

    coordinator = hass.data[const.DOMAIN][config_entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(COLD).state == STATE_UNAVAILABLE
    assert hass.states.get(HOT).state == "234"


async def test_update_value(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry)
    aioclient_mock.clear_requests()
    mock_site(aioclient_mock)

    await hass.services.async_call(
        const.DOMAIN,
        const.SERVICE_UPDATE_VALUE_CODE,
        {"value": 170},
        blocking=True,
        target={"entity_id": COLD},
    )

    # страница читается один раз, без повторного обновления координатора
    await hass.async_block_till_done()
    assert len(calls(aioclient_mock, "GET", TENANT_URL)) == 1

    posts = calls(aioclient_mock, "POST", LOGIN_URL)
    assert [
        post[2]["service1counter1"] for post in posts if post[2]["action"] == "tenant"
    ] == [170]


async def test_update_value_not_greater(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry)
    aioclient_mock.clear_requests()

    with pytest.raises(ServiceValidationError, match="не больше предыдущего"):
        await hass.services.async_call(
            const.DOMAIN,
            const.SERVICE_UPDATE_VALUE_CODE,
            {"entity_id": COLD, "value": 161},
            blocking=True,
        )

    assert aioclient_mock.call_count == 0
