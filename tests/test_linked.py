import aiohttp
import pytest
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.kvartac import const

from .conftest import LOGIN_URL, TENANT_URL, UID, calls, load_fixture, mock_site

COLD = f"sensor.{UID}_service1counter1"
HOT = f"sensor.{UID}_service5counter1"
HEATING = f"sensor.{UID}_service3counter1"
DATE = f"sensor.{UID}_date"
LINKS = [
    {"entity_id": COLD, "source": "sensor.src_cold"},
    {"entity_id": HOT, "source": "sensor.src_hot"},
]


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    options: dict,
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options=options)
    mock_site(aioclient_mock)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


def _button(hass: HomeAssistant) -> str | None:
    return next(
        (
            entry.entity_id
            for entry in er.async_get(hass).entities.values()
            if entry.platform == const.DOMAIN and entry.domain == "button"
        ),
        None,
    )


def _sent(aioclient_mock: AiohttpClientMocker) -> list[dict]:
    return [
        {key: value for key, value in post[2].items() if "counter" in key}
        for post in calls(aioclient_mock, "POST", LOGIN_URL)
        if post[2]["action"] == "tenant"
    ]


async def _send_linked(hass: HomeAssistant, data: dict | None = None, **kwargs):
    return await hass.services.async_call(
        const.DOMAIN,
        const.SERVICE_SEND_LINKED,
        data or {},
        blocking=True,
        return_response=kwargs.pop("return_response", True),
    )


async def _links_step(hass: HomeAssistant, config_entry: MockConfigEntry) -> dict:
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["step_id"] == "links"
    return result


async def test_options_links(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {})

    result = await _links_step(hass, config_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {const.CONF_LINKS: LINKS}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[const.CONF_LINKS] == LINKS
    # запись перезагружена, кнопка появилась
    assert _button(hass) is not None


async def test_options_links_duplicate(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {})

    result = await _links_step(hass, config_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            const.CONF_LINKS: [
                {"entity_id": COLD, "source": "sensor.src_cold"},
                {"entity_id": COLD, "source": "sensor.src_hot"},
            ]
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "duplicate_link"}


@pytest.mark.parametrize(
    "link",
    [
        {"entity_id": DATE, "source": "sensor.src"},
        {"entity_id": "sensor.other", "source": "sensor.src"},
        {"entity_id": COLD, "source": HOT},
    ],
    ids=["date", "foreign", "kvartac_source"],
)
async def test_options_links_not_offered(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    link: dict,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {})
    hass.states.async_set("sensor.other", "1")

    result = await _links_step(hass, config_entry)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {const.CONF_LINKS: [link]}
        )


async def test_options_links_missing_counter(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    gone = {"entity_id": f"sensor.{UID}_gone", "source": "sensor.src_cold"}
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: [gone]})

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {const.CONF_DIAGNOSTIC_SENSORS: True}
    )
    # устаревшая связь не ломает форму, а показывает ошибку
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {const.CONF_LINKS: [gone, LINKS[0]]}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "missing_meter"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {const.CONF_LINKS: [LINKS[0]]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[const.CONF_LINKS] == [LINKS[0]]
    assert config_entry.options[const.CONF_DIAGNOSTIC_SENSORS] is True


async def test_options_links_no_counters(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={const.CONF_LINKS: LINKS}
    )
    # запись ни разу не загрузилась, счетчиков в реестре нет
    mock_site(aioclient_mock, status=500)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {const.CONF_DIAGNOSTIC_SENSORS: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "no_counters"
    assert result["data_schema"] is None

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # сохраненные связи не теряются
    assert config_entry.options[const.CONF_LINKS] == LINKS
    assert config_entry.options[const.CONF_DIAGNOSTIC_SENSORS] is True


async def test_options_links_disabled_counter(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {})
    er.async_get(hass).async_update_entity(
        HOT, disabled_by=er.RegistryEntryDisabler.USER
    )

    result = await _links_step(hass, config_entry)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {const.CONF_LINKS: [LINKS[1]]}
        )


async def test_options_links_cleared(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS})
    assert _button(hass) is not None

    result = await _links_step(hass, config_entry)
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert const.CONF_LINKS not in config_entry.options
    assert _button(hass) is None


async def test_send_linked(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS})
    hass.states.async_set("sensor.src_cold", "170.7", {ATTR_UNIT_OF_MEASUREMENT: "m³"})
    hass.states.async_set("sensor.src_hot", "250500", {ATTR_UNIT_OF_MEASUREMENT: "L"})
    aioclient_mock.clear_requests()
    mock_site(aioclient_mock)

    response = await _send_linked(hass)

    assert response["code"] == 0
    assert [result["code"] for result in response["results"]] == [0]
    assert response["results"][0]["entity_ids"] == [COLD, HOT]
    # все показания записи уходят одним запросом
    assert _sent(aioclient_mock) == [{"service1counter1": 170, "service5counter1": 250}]


async def test_send_linked_unavailable_source(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS})
    hass.states.async_set("sensor.src_cold", "170", {ATTR_UNIT_OF_MEASUREMENT: "m³"})
    hass.states.async_set("sensor.src_hot", "unavailable")

    response = await _send_linked(hass)

    codes = {result["entity_ids"][0]: result["code"] for result in response["results"]}
    assert codes == {COLD: 0, HOT: -4}
    assert response["code"] == -4
    assert _sent(aioclient_mock) == [{"service1counter1": 170}]


async def test_send_linked_incompatible_unit(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS[:1]})
    hass.states.async_set("sensor.src_cold", "170", {ATTR_UNIT_OF_MEASUREMENT: "kWh"})

    response = await _send_linked(hass)

    assert response["code"] == -5
    assert not _sent(aioclient_mock)


async def test_send_linked_without_links(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {})

    with pytest.raises(ServiceValidationError):
        await _send_linked(hass)


async def test_send_linked_conversion_rounding(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    links = [{"entity_id": HEATING, "source": "sensor.src_heating"}]
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: links})
    # 31,38 МВт·ч ровно 27 Гкал, без округления пересчёт дает 26,999…
    hass.states.async_set(
        "sensor.src_heating", "31.38", {ATTR_UNIT_OF_MEASUREMENT: "MWh"}
    )

    await _send_linked(hass)

    assert _sent(aioclient_mock) == [{"service3counter1": 27}]


async def test_send_linked_fractional_counter(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    links = [{"entity_id": HEATING, "source": "sensor.src_heating"}]
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: links})
    # прежние 18,9033 сравниваются без дробной части: 18 не меньше 18
    hass.states.async_set(
        "sensor.src_heating", "18.95", {ATTR_UNIT_OF_MEASUREMENT: "Gcal"}
    )

    response = await _send_linked(hass)

    assert response["code"] == 0
    assert _sent(aioclient_mock) == [{"service3counter1": 18}]


@pytest.mark.parametrize("state", ["nan", "inf", "0", "-5"])
async def test_send_linked_invalid_source_value(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state: str,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS[:1]})
    hass.states.async_set("sensor.src_cold", state, {ATTR_UNIT_OF_MEASUREMENT: "m³"})

    response = await _send_linked(hass)

    assert response["code"] == -4
    assert not _sent(aioclient_mock)


@pytest.mark.parametrize(
    ("state", "code", "sent"),
    [
        ("161", 0, [{"service1counter1": 161}]),
        ("1000000", -3, []),
    ],
    ids=["same", "too_large"],
)
async def test_send_linked_value_check(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    state: str,
    code: int,
    sent: list,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS[:1]})
    hass.states.async_set("sensor.src_cold", state, {ATTR_UNIT_OF_MEASUREMENT: "m³"})

    response = await _send_linked(hass)

    assert response["code"] == code
    assert _sent(aioclient_mock) == sent


async def test_send_linked_missing_meter(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    links = [{"entity_id": f"sensor.{UID}_gone", "source": "sensor.src_cold"}]
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: links})

    response = await _send_linked(hass)

    assert [result["code"] for result in response["results"]] == [-6]
    assert f"sensor.{UID}_gone" in response["message"]


async def test_send_linked_connection_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS})
    hass.states.async_set("sensor.src_cold", "170", {ATTR_UNIT_OF_MEASUREMENT: "m³"})
    hass.states.async_set("sensor.src_hot", "250", {ATTR_UNIT_OF_MEASUREMENT: "m³"})
    aioclient_mock.clear_requests()
    aioclient_mock.post(LOGIN_URL, exc=aiohttp.ClientError)

    response = await _send_linked(hass)

    assert [result["code"] for result in response["results"]] == [-1]
    assert response["results"][0]["entity_ids"] == [COLD, HOT]


async def test_send_linked_updates_once(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS})
    hass.states.async_set("sensor.src_cold", "170", {ATTR_UNIT_OF_MEASUREMENT: "m³"})
    hass.states.async_set("sensor.src_hot", "250", {ATTR_UNIT_OF_MEASUREMENT: "m³"})
    tenant = (
        load_fixture("tenant.html")
        .replace("00161", "00170")
        .replace("000234", "000250")
    )
    aioclient_mock.clear_requests()
    aioclient_mock.post(LOGIN_URL, text="")
    aioclient_mock.get(TENANT_URL, text=tenant)
    updates = []
    hass.bus.async_listen("state_changed", lambda event: updates.append(event))

    await _send_linked(hass)
    await hass.async_block_till_done()

    assert hass.states.get(COLD).state == "170"
    assert hass.states.get(HOT).state == "250"
    # состояние пишется один раз после всех отправок, а не после каждой
    assert len([e for e in updates if e.data["entity_id"] == COLD]) == 1


@pytest.mark.parametrize(
    ("throws", "raises"),
    [(True, True), (False, False)],
    ids=["throws", "no_throws"],
)
async def test_send_linked_throws(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    throws: bool,
    raises: bool,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS})
    hass.states.async_set("sensor.src_cold", "170", {ATTR_UNIT_OF_MEASUREMENT: "m³"})
    hass.states.async_set("sensor.src_hot", "unavailable")

    if raises:
        with pytest.raises(HomeAssistantError, match="sensor.src_hot недоступен"):
            await _send_linked(hass, {"throws": throws}, return_response=False)
    else:
        assert (
            await _send_linked(hass, {"throws": throws}, return_response=False) is None
        )
    assert _sent(aioclient_mock) == [{"service1counter1": 170}]


@pytest.mark.parametrize(
    ("options", "exists"),
    [
        ({const.CONF_LINKS: LINKS}, True),
        ({}, False),
    ],
    ids=["links", "no_links"],
)
async def test_button_created(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    options: dict,
    exists: bool,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, options)

    assert (_button(hass) is not None) is exists


async def test_button_press(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS})
    hass.states.async_set("sensor.src_cold", "170", {ATTR_UNIT_OF_MEASUREMENT: "m³"})
    hass.states.async_set("sensor.src_hot", "250", {ATTR_UNIT_OF_MEASUREMENT: "m³"})

    await hass.services.async_call(
        "button", "press", {"entity_id": _button(hass)}, blocking=True
    )

    assert _sent(aioclient_mock) == [{"service1counter1": 170, "service5counter1": 250}]


async def test_button_press_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS[:1]})
    hass.states.async_set("sensor.src_cold", "1", {ATTR_UNIT_OF_MEASUREMENT: "m³"})

    with pytest.raises(HomeAssistantError, match="меньше предыдущего"):
        await hass.services.async_call(
            "button", "press", {"entity_id": _button(hass)}, blocking=True
        )
    assert not _sent(aioclient_mock)


async def test_options_links_preview(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {const.CONF_LINKS: LINKS})
    hass.states.async_set(
        "sensor.src_cold",
        "170.7",
        {ATTR_UNIT_OF_MEASUREMENT: "m³", "friendly_name": "Источник ХВС"},
    )
    hass.states.async_set("sensor.src_hot", "1", {ATTR_UNIT_OF_MEASUREMENT: "m³"})

    result = await _links_step(hass, config_entry)

    preview = result["description_placeholders"]["preview"]
    assert "**ХВС, 1 33334566**: 170 (сейчас 161) ← Источник ХВС" in preview
    assert "меньше предыдущего" in preview


async def test_options_links_preview_empty(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await _setup(hass, aioclient_mock, config_entry, {})

    result = await _links_step(hass, config_entry)

    assert result["description_placeholders"] == {"preview": ""}
