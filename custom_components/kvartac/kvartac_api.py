"""Kvarta-C API"""
import logging
from typing import Final, TypedDict
from datetime import datetime, date
import re

from homeassistant import exceptions

import aiohttp
from bs4 import BeautifulSoup, Tag

_LOGGER = logging.getLogger(__name__)


class Counter(TypedDict):
    """Counter holder"""

    id: str
    service: str
    value: int | float


class KvartaCApi:
    """Kvarta-C API access implementation"""

    BASE_URL: Final = "https://www.kvarta-c.ru/voda.php"
    _LOGIN_URL: Final = BASE_URL + "?action=login"
    _TENANT_URL: Final = BASE_URL + "?action=tenant"

    COUNTER_VALUE = "value"
    COUNTER_ID = "id"
    COUNTER_SERVICE = "service"

    counters: dict[str, Counter]

    def __init__(
        self,
        session: aiohttp.ClientSession,
        organisation_id: str,
        account_id: str,
        password: str = None,
    ):
        self._session = session
        self.organisation_id = organisation_id
        self.account_id = account_id
        self.password = (
            organisation_id if password is None or password == "" else password
        )
        self.account = ""
        self.organisation = ""
        self.prev_save_date: date = None
        self.counters = {}

    @staticmethod
    def _text(tag: Tag | None) -> str:
        if tag is None:
            return ""
        return re.sub("\\s+", " ", tag.get_text()).strip()

    def _parse_account(self, soup: BeautifulSoup):
        _LOGGER.debug("Parsing account")

        for row in soup.select("div.cab-account__row"):
            label = self._text(row.select_one(".cab-account__label"))
            value = self._text(row.select_one(".cab-account__value"))
            if "cab-account__row--full" in row.get("class", []):
                self.organisation = label.replace('" ', '"').replace('",', '"')
                _LOGGER.debug("Organisation: %s", self.organisation)
            elif label.startswith("Лицевой"):
                # TODO check with self.account_id
                _LOGGER.debug("Account ID: %s", value)
            elif label.startswith("Плательщик"):
                self.account = value
                _LOGGER.debug("Account: %s", self.account)

        prev_save_date = self._text(soup.select_one(".cab-note b"))
        try:
            self.prev_save_date = datetime.strptime(prev_save_date, "%d.%m.%Y").date()
        except ValueError:
            _LOGGER.warning("Can't parse previous save date: %s", prev_save_date)
            self.prev_save_date = None
        _LOGGER.debug("Previous save date: %s", self.prev_save_date)

    def _parse_counter(self, row: Tag):
        counter = row.select_one("span.meters__new input[name]")
        if counter is None:
            _LOGGER.debug("No counter found")
            return
        counter = counter.attrs["name"]

        service = self._text(row.select_one("span.meters__name"))
        if service.endswith(":"):
            service = service[:-1].strip()

        # значения могут быть с запятой, например 000379,90 (#2)
        value = self._text(row.select_one("span.meters__old")).replace(",", ".")
        try:
            value = float(value) if value.find(".") != -1 else int(value)
        except ValueError:
            _LOGGER.warning("Can't parse value of %s: %s", counter, value)
            return

        cid = self._text(row.select_one("span.meters__sn"))
        if cid.startswith("№"):
            cid = cid[1:].strip()
        if cid == "":
            cid = counter[-1]

        self.counters[counter] = {
            self.COUNTER_VALUE: value,
            self.COUNTER_ID: cid,
            self.COUNTER_SERVICE: service,
        }

        _LOGGER.debug("Counter %s[%s]=%s", counter, cid, value)

    def _parse_html(self, html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")

        # после обновления дизайна сайта от 2026 года
        rows = soup.select("div.meters__row")
        if len(rows) == 0:
            return False

        self._parse_account(soup)

        _LOGGER.debug("Found %d counters", len(rows))

        counters = self.counters
        self.counters = {}
        for row in rows:
            self._parse_counter(row)

        if len(self.counters) == 0:
            self.counters = counters
            return False

        return True

    async def _async_login(self) -> None:
        data = {
            "action": "login",
            "subaction": "enter",
            "usertype": "tenant",
            "tsgid": self.organisation_id,
            "accountid": self.account_id,
            "password": self.password,
        }
        _LOGGER.debug("POST %s: %s", self._LOGIN_URL, str(data))
        resp = await self._session.post(self._LOGIN_URL, data=data)
        if resp.status != 200:
            raise ApiError

    async def _async_fetch(self) -> None:
        resp = await self._session.get(self._TENANT_URL)
        if resp.status != 200:
            raise ApiError

        content = await resp.text()
        res = self._parse_html(content)
        if not res:
            _LOGGER.error(content)
            raise ApiAuthError

    async def _async_update(self, counter_id: str, value: int):
        resp = await self._session.post(
            self._LOGIN_URL,
            data={
                "action": "tenant",
                "subaction": "tenantedit",
                "usertype": "tenant",
                counter_id: value,
            },
        )

        if resp.status != 200:
            raise ApiError

        # text = await resp.text()
        # _LOGGER.debug("result of update is: %s", text)
        # TODO check "Data is updated." to be sure that update was success

    async def async_fetch(self) -> None:
        """Login and fetch new data"""
        await self._async_login()
        await self._async_fetch()

    async def async_update(self, counter_id: str, value: int):
        """Login, update and fetch new counter value"""
        await self._async_login()
        await self._async_update(counter_id, value)
        await self._async_fetch()

    def parse(self, session) -> bool:
        session.post(
            self._LOGIN_URL,
            data={
                "action": "login",
                "subaction": "enter",
                "usertype": "tenant",
                "tsgid": self.organisation_id,
                "accountid": self.account_id,
                "password": self.password,
            },
        )
        page = session.get(self._TENANT_URL)
        return self._parse_html(page.content)

    def parse_file(self, filename: str, encoding: str = "utf-8"):
        with open(filename, "r", encoding=encoding) as file:
            self._parse_html(file.read())

    @property
    def uid(self):
        """Return unique id."""
        return f"{self.organisation_id}_{self.account_id}"


class ApiError(exceptions.HomeAssistantError):
    """Error to indicate api error."""


class ApiAuthError(exceptions.HomeAssistantError):
    """Error to indicate auth error."""
