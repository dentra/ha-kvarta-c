from datetime import timedelta

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.kvartac import config_flow, const

from .conftest import (
    ACC_ID,
    LOGIN_URL,
    ORG_ID,
    PASSWD,
    TENANT_URL,
    UID,
    calls,
    load_fixture,
    mock_site,
)

USER_INPUT = {
    const.CONF_ORG_ID: ORG_ID,
    const.CONF_ACC_ID: ACC_ID,
    const.CONF_PASSWD: PASSWD,
}


async def _start_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        const.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return result["flow_id"]


async def test_user_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_site(aioclient_mock)
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Невский пр. д.1, кв. 13"
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == f"{const.DOMAIN}_{UID}"


async def test_user_flow_demo(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_site(aioclient_mock)
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {**USER_INPUT, const.CONF_PASSWD: config_flow.DEMO_PASSWD}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        const.CONF_ORG_ID: config_flow.DEMO_ORG_ID,
        const.CONF_ACC_ID: config_flow.DEMO_ACC_ID,
        const.CONF_PASSWD: config_flow.DEMO_PASSWD,
    }
    assert calls(aioclient_mock, "POST", LOGIN_URL)[0][2]["tsgid"] == "0000"


@pytest.mark.parametrize(
    ("user_input", "error"),
    [
        ({const.CONF_ORG_ID: "123"}, "invalid_org_id"),
        ({const.CONF_ACC_ID: ""}, "invalid_acc_id"),
    ],
)
async def test_user_flow_invalid_input(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    user_input: dict,
    error: str,
) -> None:
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {**USER_INPUT, **user_input}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    ("tenant", "status", "error"),
    [
        ("unauth.html", 200, "invalid_auth"),
        ("tenant.html", 500, "api_error"),
    ],
)
async def test_user_flow_api_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    tenant: str,
    status: int,
    error: str,
) -> None:
    mock_site(aioclient_mock, tenant, status)
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    mock_site(aioclient_mock)
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_site(aioclient_mock)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["description_placeholders"] == {
        "acc_info": "Невский пр. д.1, кв. 13",
        "org_info": 'ТСЖ "Колизей"',
    }

    options = {
        const.CONF_UPDATE_INTERVAL: {"days": 1, "hours": 2, "minutes": 0, "seconds": 0},
        const.CONF_PREV_DATE_SENSOR: False,
        const.CONF_DIAGNOSTIC_SENSORS: True,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == options

    coordinator = hass.data[const.DOMAIN][config_entry.entry_id]
    assert coordinator.update_interval == timedelta(days=1, hours=2)


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(LOGIN_URL, exc=aiohttp.ClientError)
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow_not_loaded(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_site(aioclient_mock, status=500)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {
        "acc_info": "Невский пр. д.1, кв. 13",
        "org_info": "",
    }


async def _start_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> str:
    mock_site(aioclient_mock, "unauth.html")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["step_id"] == "reauth_confirm"
    assert flows[0]["context"]["source"] == config_entries.SOURCE_REAUTH
    aioclient_mock.clear_requests()
    return flows[0]["flow_id"]


async def test_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    flow_id = await _start_reauth(hass, aioclient_mock, config_entry)
    mock_site(aioclient_mock)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {const.CONF_PASSWD: "new"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data == {**USER_INPUT, const.CONF_PASSWD: "new"}
    assert config_entry.state is config_entries.ConfigEntryState.LOADED
    assert calls(aioclient_mock, "POST", LOGIN_URL)[0][2]["password"] == "new"


async def test_reauth_demo_password(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    flow_id = await _start_reauth(hass, aioclient_mock, config_entry)
    mock_site(aioclient_mock)

    await hass.config_entries.flow.async_configure(
        flow_id, {const.CONF_PASSWD: config_flow.DEMO_PASSWD}
    )
    await hass.async_block_till_done()

    # пароль demo не подменяет аккаунт на демонстрационный
    assert calls(aioclient_mock, "POST", LOGIN_URL)[0][2]["tsgid"] == ORG_ID
    assert config_entry.data[const.CONF_ORG_ID] == ORG_ID


@pytest.mark.parametrize(
    ("tenant", "status", "error"),
    [
        ("unauth.html", 200, "invalid_auth"),
        ("tenant.html", 500, "api_error"),
    ],
)
async def test_reauth_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    tenant: str,
    status: int,
    error: str,
) -> None:
    flow_id = await _start_reauth(hass, aioclient_mock, config_entry)
    mock_site(aioclient_mock, tenant, status)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {const.CONF_PASSWD: "new"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert config_entry.data[const.CONF_PASSWD] == PASSWD
