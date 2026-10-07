from unittest.mock import Mock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.kvartac import const

from .conftest import mock_site


async def test_setup_and_unload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_site(aioclient_mock)
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.entry_id in hass.data[const.DOMAIN]

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert config_entry.entry_id not in hass.data[const.DOMAIN]


async def test_setup_auth_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_site(aioclient_mock, "unauth.html")
    config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert [
        flow["step_id"]
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == SOURCE_REAUTH
    ] == ["reauth_confirm"]


async def test_setup_api_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_site(aioclient_mock, status=500)
    config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert config_entry.entry_id not in hass.data[const.DOMAIN]


async def test_own_session(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_site(aioclient_mock)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # cookie входа своя у каждой записи, иначе вход другого счета
    # может попасть между входом и отправкой показаний
    session = hass.data[const.DOMAIN][config_entry.entry_id].api._session
    assert session is not async_get_clientsession(hass)


@pytest.mark.parametrize("status", [200, 500], ids=["unload", "setup_retry"])
async def test_own_session_closed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    status: int,
) -> None:
    sessions = []

    def create_session(hass: HomeAssistant, *args, auto_cleanup_method=None, **kwargs):
        # мок HA не регистрирует очистку, а настоящая фабрика регистрирует
        session = aioclient_mock.create_session(hass.loop)
        # закрывать сессию HA должен сам, вызов close пишет предупреждение
        object.__setattr__(session, "close", Mock(side_effect=AssertionError))
        if auto_cleanup_method:
            auto_cleanup_method(hass, session)
        sessions.append(session)
        return session

    mock_site(aioclient_mock, status=status)
    config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.helpers.aiohttp_client._async_create_clientsession",
        side_effect=create_session,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    (session,) = sessions
    if status == 200:
        assert not session.closed
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
    else:
        assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert session.closed
    session.close.assert_not_called()
