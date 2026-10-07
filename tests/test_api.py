from datetime import date

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.kvartac.kvartac_api import ApiAuthError, ApiError, KvartaCApi

from .conftest import (
    ACC_ID,
    LOGIN_URL,
    ORG_ID,
    PASSWD,
    TENANT_URL,
    calls,
    load_fixture,
    mock_site,
)

COUNTER_ROW = """
<div class="meters__row">
  <span class="meters__name">{name}</span>
  <span class="meters__old">{value}</span>
  <span class="meters__new"><input type="text" name="{counter}"></span>
  <span class="meters__sn">{sn}</span>
</div>
"""


def _page(*rows: str) -> str:
    return f"""
<div class="cab-account">
  <div class="cab-account__row">
    <span class="cab-account__label">Плательщик</span>
    <span class="cab-account__value">Иванов</span>
  </div>
  <div class="cab-account__row cab-account__row--full">
    <span class="cab-account__label">ТСЖ "Тест"</span>
  </div>
</div>
<p class="cab-note">Предыдущие показания от <b>01.02.2026</b></p>
<div class="meters">{"".join(rows)}</div>
"""


def _row(counter: str, value: str, name: str = "ХВС", sn: str = "№ 1") -> str:
    return COUNTER_ROW.format(counter=counter, value=value, name=name, sn=sn)


def _api(hass: HomeAssistant | None = None, password: str | None = PASSWD):
    session = async_get_clientsession(hass) if hass else None
    return KvartaCApi(session, ORG_ID, ACC_ID, password)


def test_parse_tenant_page() -> None:
    api = _api()
    assert api._parse_html(load_fixture("tenant.html"))

    assert api.account == "Невский пр. д.1, кв. 13"
    assert api.organisation == 'ТСЖ "Колизей"'
    assert api.prev_save_date == date(2023, 3, 25)
    assert api.counters == {
        "service1counter1": {"value": 161, "id": "33334566", "service": "ХВС, 1"},
        "service1counter2": {"value": 125, "id": "2043566", "service": "ХВС, 2"},
        "service3counter1": {
            "value": 18.9033,
            "id": "5463457",
            "service": "Отопление",
        },
        "service5counter1": {"value": 234, "id": "04555777", "service": "ГВС, 1"},
        "service5counter2": {"value": 89, "id": "04555788", "service": "ГВС, 2"},
    }


def test_parse_unauthorized_page() -> None:
    assert not _api()._parse_html(load_fixture("unauth.html"))


def test_parse_value_with_comma() -> None:
    api = _api()
    assert api._parse_html(_page(_row("service1counter1", "000379,90")))
    assert api.counters["service1counter1"]["value"] == 379.9


def test_parse_service_and_serial() -> None:
    api = _api()
    assert api._parse_html(_page(_row("service2counter3", "1", "Газ:", "")))
    assert api.counters["service2counter3"] == {
        "value": 1,
        "id": "3",
        "service": "Газ",
    }


def test_parse_without_counters() -> None:
    api = _api()
    assert api._parse_html(_page())
    assert api.account == "Иванов"
    assert api.counters == {}


def test_parse_skips_bad_counter() -> None:
    api = _api()
    assert api._parse_html(
        _page(_row("service1counter1", "abc"), _row("service1counter2", "12"))
    )
    assert list(api.counters) == ["service1counter2"]


def test_parse_bad_date() -> None:
    api = _api()
    assert api._parse_html(_page().replace("01.02.2026", "-"))
    assert api.prev_save_date is None


def test_parse_failure_keeps_data() -> None:
    api = _api()
    assert api._parse_html(load_fixture("tenant.html"))
    counters = api.counters

    with pytest.raises(ApiError):
        api._parse_html(_page(_row("service1counter1", "abc")))

    assert api.counters == counters
    assert api.account == "Невский пр. д.1, кв. 13"


def test_empty_password_uses_organisation() -> None:
    assert _api(password="").password == ORG_ID
    assert _api(password=None).password == ORG_ID


async def test_fetch(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_site(aioclient_mock)
    api = _api(hass)

    await api.async_fetch()

    assert len(api.counters) == 5
    login = calls(aioclient_mock, "POST", LOGIN_URL)
    assert len(login) == 1
    assert login[0][2] == {
        "action": "login",
        "subaction": "enter",
        "usertype": "tenant",
        "tsgid": ORG_ID,
        "accountid": ACC_ID,
        "password": PASSWD,
    }


async def test_fetch_auth_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_site(aioclient_mock, "unauth.html")
    with pytest.raises(ApiAuthError):
        await _api(hass).async_fetch()

    # страница сайта пишется в лог только на уровне debug
    assert not [
        r
        for r in caplog.records
        if "Group mismatch" in r.getMessage() and r.levelno > 10
    ]


async def test_fetch_http_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_site(aioclient_mock, status=500)
    with pytest.raises(ApiError):
        await _api(hass).async_fetch()


async def test_login_http_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(LOGIN_URL, status=500)
    with pytest.raises(ApiError):
        await _api(hass).async_fetch()
    assert not calls(aioclient_mock, "GET", TENANT_URL)


async def test_update(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    mock_site(aioclient_mock)
    api = _api(hass)

    await api.async_update("service1counter1", 170)

    login = calls(aioclient_mock, "POST", LOGIN_URL)
    assert len(login) == 2
    assert login[1][2] == {
        "action": "tenant",
        "subaction": "tenantedit",
        "usertype": "tenant",
        "service1counter1": 170,
    }
    assert len(calls(aioclient_mock, "GET", TENANT_URL)) == 1
