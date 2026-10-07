import aiohttp
import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.kvartac import const

from .conftest import LOGIN_URL, TENANT_URL, UID, calls, mock_site

COLD = f"sensor.{UID}_service1counter1"
HOT = f"sensor.{UID}_service5counter1"
DATE = f"sensor.{UID}_date"


@pytest.fixture(autouse=True)
async def setup_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_site(aioclient_mock)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    aioclient_mock.clear_requests()
    mock_site(aioclient_mock)


async def _call(hass: HomeAssistant, data: dict, **kwargs):
    return await hass.services.async_call(
        const.DOMAIN,
        const.SERVICE_UPDATE_VALUE_CODE,
        data,
        blocking=True,
        return_response=kwargs.pop("return_response", True),
        **kwargs,
    )


def _sent(aioclient_mock: AiohttpClientMocker) -> list[dict]:
    return [
        {key: value for key, value in post[2].items() if "counter" in key}
        for post in calls(aioclient_mock, "POST", LOGIN_URL)
        if post[2]["action"] == "tenant"
    ]


async def test_update_value(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _call(hass, {"value": 170}, target={"entity_id": COLD}, return_response=False)

    # страница читается один раз, без повторного обновления координатора
    await hass.async_block_till_done()
    assert len(calls(aioclient_mock, "GET", TENANT_URL)) == 1
    assert _sent(aioclient_mock) == [{"service1counter1": 170}]


async def test_update_value_less(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    with pytest.raises(HomeAssistantError, match="меньше предыдущего"):
        await _call(hass, {"entity_id": COLD, "value": 160}, return_response=False)

    assert aioclient_mock.call_count == 0


async def test_update_value_same(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    # неизменившиеся показания можно передать повторно
    response = await _call(hass, {"entity_id": COLD, "value": 161})

    assert response["code"] == 0
    assert _sent(aioclient_mock) == [{"service1counter1": 161}]


async def test_update_value_too_large(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    with pytest.raises(vol.Invalid):
        await _call(hass, {"entity_id": COLD, "value": 1000000})

    assert aioclient_mock.call_count == 0


async def test_values_one_request(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    response = await _call(
        hass,
        {
            "values": [
                {"entity_id": COLD, "value": 170},
                {"entity_id": HOT, "value": 250},
            ]
        },
    )

    assert response == {
        "code": 0,
        "message": const.MESSAGE_SUCCESS,
        "results": [
            {
                "entity_ids": [COLD, HOT],
                "code": 0,
                "message": const.MESSAGE_SUCCESS,
                "payload": {"service1counter1": 170, "service5counter1": 250},
            }
        ],
    }
    assert _sent(aioclient_mock) == [{"service1counter1": 170, "service5counter1": 250}]
    assert len(calls(aioclient_mock, "GET", TENANT_URL)) == 1


async def test_values_less_skips_counter(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    response = await _call(
        hass,
        {
            "values": [
                {"entity_id": COLD, "value": 100},
                {"entity_id": HOT, "value": 250},
            ]
        },
    )

    assert response["code"] == -3
    codes = {result["entity_ids"][0]: result["code"] for result in response["results"]}
    assert codes == {COLD: -3, HOT: 0}
    assert _sent(aioclient_mock) == [{"service5counter1": 250}]


@pytest.mark.parametrize(
    "data",
    [
        {"value": 170, "values": [{"entity_id": COLD, "value": 170}]},
        {},
        {"entity_id": COLD, "values": [{"entity_id": COLD, "value": 170}]},
        {"values": [{"entity_id": "sensor.unknown", "value": 170}]},
        {"values": [{"entity_id": DATE, "value": 170}]},
        {"entity_id": DATE, "value": 170},
        {"entity_id": [COLD, "sensor.unknown"], "value": 170},
        {"entity_id": "none", "value": 170},
        {
            "values": [
                {"entity_id": COLD, "value": 170},
                {"entity_id": COLD, "value": 171},
            ]
        },
    ],
    ids=[
        "value_and_values",
        "nothing",
        "values_and_target",
        "unknown",
        "date",
        "date_target",
        "unknown_target",
        "none_target",
        "duplicate",
    ],
)
async def test_update_value_invalid_call(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, data: dict
) -> None:
    with pytest.raises((ServiceValidationError, vol.Invalid)):
        await _call(hass, data)

    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize("throws", [True, False])
async def test_values_throws(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    throws: bool,
) -> None:
    data = {
        "values": [
            {"entity_id": COLD, "value": 100},
            {"entity_id": HOT, "value": 250},
        ],
        "throws": throws,
    }

    if throws:
        with pytest.raises(HomeAssistantError, match="меньше предыдущего"):
            await _call(hass, data, return_response=False)
    else:
        assert await _call(hass, data, return_response=False) is None
        assert "меньше предыдущего" in caplog.text
    assert _sent(aioclient_mock) == [{"service5counter1": 250}]


async def test_values_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.post(LOGIN_URL, exc=aiohttp.ClientConnectionError())

    response = await _call(hass, {"values": [{"entity_id": COLD, "value": 170}]})

    assert response["code"] == -1
    assert response["results"][0]["entity_ids"] == [COLD]


@pytest.mark.parametrize(
    "target",
    [{"entity_id": "all"}, "device"],
    ids=["all", "device"],
)
async def test_update_value_target_skips_date(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    target: dict | str,
) -> None:
    if target == "device":
        registry = dr.async_get(hass)
        (device,) = dr.async_entries_for_config_entry(registry, config_entry.entry_id)
        target = {"device_id": device.id}

    response = await _call(hass, {"value": 250}, target=target)

    # сенсор даты не мешает передаче по всем счетчикам
    assert response["code"] == 0
    assert DATE not in response["results"][0]["entity_ids"]
    assert _sent(aioclient_mock) == [
        {
            "service1counter1": 250,
            "service1counter2": 250,
            "service3counter1": 250,
            "service5counter1": 250,
            "service5counter2": 250,
        }
    ]


async def test_update_value_target_unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    coordinator = hass.data[const.DOMAIN][config_entry.entry_id]
    del coordinator.api.counters["service5counter1"]

    response = await _call(
        hass, {"value": 250}, target={"entity_id": [COLD, HOT]}, return_response=True
    )

    codes = {result["entity_ids"][0]: result["code"] for result in response["results"]}
    assert codes[HOT] != 0
    assert codes[COLD] == 0
    assert "недоступен" in response["message"]
    assert _sent(aioclient_mock) == [{"service1counter1": 250}]


async def test_values_refetch_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.post(LOGIN_URL, text="")
    aioclient_mock.get(TENANT_URL, exc=aiohttp.ClientConnectionError())

    # показания уже ушли, ошибка чтения страницы не считается неудачей
    response = await _call(hass, {"values": [{"entity_id": COLD, "value": 170}]})

    assert response["code"] == 0
    assert _sent(aioclient_mock) == [{"service1counter1": 170}]


async def test_values_refetch_auth_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.post(LOGIN_URL, text="")
    aioclient_mock.get(TENANT_URL, text="<html></html>")

    # без входа сайт отвечает 200, но показания не принимает
    response = await _call(hass, {"values": [{"entity_id": COLD, "value": 170}]})

    assert response["code"] == const.ErrorCode.AUTH
    await hass.async_block_till_done()
    assert any(config_entry.async_get_active_flows(hass, {"reauth"}))


@pytest.mark.parametrize(
    ("data", "target"),
    [
        ({"value": 250}, {"entity_id": COLD}),
        ({"value": "250"}, {"entity_id": [COLD, HOT]}),
        ({"entity_id": [COLD, HOT], "value": 250}, None),
        ({"value": 250}, "area"),
    ],
    ids=["entity", "entities_value_str", "data_entity_id", "area"],
)
async def test_update_value_legacy_format(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    data: dict,
    target: dict | str | None,
) -> None:
    # прежний формат из README: target + value, без ответа
    if target == "area":
        area = ar.async_get(hass).async_create("Квартира")
        registry = dr.async_get(hass)
        (device,) = dr.async_entries_for_config_entry(registry, config_entry.entry_id)
        registry.async_update_device(device.id, area_id=area.id)
        target = {"area_id": area.id}
        expected = {
            "service1counter1": 250,
            "service1counter2": 250,
            "service3counter1": 250,
            "service5counter1": 250,
            "service5counter2": 250,
        }
    elif COLD in str(target) and HOT not in str(target):
        expected = {"service1counter1": 250}
    else:
        expected = {"service1counter1": 250, "service5counter1": 250}

    assert await _call(hass, data, target=target, return_response=False) is None

    assert _sent(aioclient_mock) == [expected]
