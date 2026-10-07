from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.kvartac import const
from custom_components.kvartac.kvartac_api import KvartaCApi

LOGIN_URL = KvartaCApi.BASE_URL + "?action=login"
TENANT_URL = KvartaCApi.BASE_URL + "?action=tenant"

ORG_ID = "1234"
ACC_ID = "000000001"
PASSWD = "secret"
UID = f"{ORG_ID}_{ACC_ID}"

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def calls(aioclient_mock: AiohttpClientMocker, method: str, url: str) -> list:
    return [
        call
        for call in aioclient_mock.mock_calls
        if call[0].upper() == method and str(call[1]) == url
    ]


def mock_site(
    aioclient_mock: AiohttpClientMocker,
    tenant: str = "tenant.html",
    status: int = 200,
) -> None:
    aioclient_mock.post(LOGIN_URL, text=load_fixture("login.html"))
    aioclient_mock.get(TENANT_URL, status=status, text=load_fixture(tenant))


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=const.DOMAIN,
        unique_id=f"{const.DOMAIN}_{UID}",
        title="Невский пр. д.1, кв. 13",
        data={
            const.CONF_ORG_ID: ORG_ID,
            const.CONF_ACC_ID: ACC_ID,
            const.CONF_PASSWD: PASSWD,
        },
    )
