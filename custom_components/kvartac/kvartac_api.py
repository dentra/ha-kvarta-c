"""Kvarta-C API"""
import logging
from typing import Final, TypedDict

from homeassistant import exceptions

import aiohttp
from bs4 import BeautifulSoup, ResultSet, Tag

_LOGGER = logging.getLogger(__name__)


class Counter(TypedDict):
    """Counter holder"""

    id: str
    service: str
    value: int


class KvartaCApi:
    """Kvarta-C API access implementation"""

    BASE_URL: Final = "http://www.kvarta-c.ru/voda.php"
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
        self.prev_save_date = ""
        self.counters = {}

    def _parse_account(self, links: ResultSet[Tag]):
        _LOGGER.debug("Parsing account")

        account_str = "Номер лицевого счета:"
        text = links[1].get_text().strip()
        if not text.startswith(account_str):
            _LOGGER.warning("Can't parse account, data: %s", text)
            return

        acc_id = text[len(account_str) :].strip()
        # TODO check with self.account_id
        _LOGGER.debug("Account ID: %s", acc_id)

        self.account = links[2].get_text().strip()
        _LOGGER.debug("Account: %s", self.account)

        self.organisation = links[3].get_text().replace('" ', '"').replace('",', '"')
        _LOGGER.debug("Organisation: %s", self.organisation)

        self.prev_save_date = links[5].find("b").get_text().strip()
        _LOGGER.debug("Previous save date: %s", self.prev_save_date)

    def _parse_counter(self, links: ResultSet[Tag], service: str, start_index: int):
        _LOGGER.debug("Parsing counter for %s at %d", service, start_index)
        item = links[start_index + 1]
        counter = item.find("input")
        if not counter:
            _LOGGER.debug("No counter found")
            return
        counter = counter.attrs["name"]

        value = int(links[start_index].get_text().strip())

        cid = item.find("font")
        if cid is not None:
            cid = cid.get_text()
            if cid.startswith("№"):
                cid = cid[1:]
            cid = cid.strip()
        if cid is None or cid == "":
            cid = counter[-1]

        self.counters[counter] = {
            self.COUNTER_VALUE: value,
            self.COUNTER_ID: cid,
            self.COUNTER_SERVICE: service,
        }

        _LOGGER.debug("Counter %s[%s]=%d", counter, cid, value)

    def _parse_service(self, links: ResultSet[Tag], service_id: int, start_index: int):
        _LOGGER.debug("Parsing service %d", service_id)
        service = links[start_index + 0].get_text().strip()
        if service.endswith(":"):
            service = service[:-1].strip()

        start_index += 1

        for _ in range(4):
            self._parse_counter(links, service, start_index)
            start_index += 2

    def _parse_html(self, html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")

        links = soup.select("font.medtxt")
        if len(links) == 0:
            return False

        self._parse_account(links)

        service_count = 0
        for inp in soup.select("input[name]"):
            name = inp.attrs["name"]
            find = "service"
            if name.startswith(find):
                service_no = int(name[len(find) : len(find) + 1])
                service_count = max(service_count, service_no)
        _LOGGER.debug("Found %d services", service_count)

        for i in range(service_count):
            self._parse_service(links, i + 1, 27 + (i * 10))

        return True

    async def _async_login(self) -> None:
        resp = await self._session.post(
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
        if resp.status != 200:
            raise ApiError

    async def _async_fetch(self) -> None:
        resp = await self._session.get(self._TENANT_URL)
        if resp.status != 200:
            raise ApiError

        content = await resp.text()

        res = self._parse_html(content)
        if not res:
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

    def parse_file(self, filename: str):
        with open(filename, "r", encoding="utf-8") as file:
            self._parse_html(file.read())

    @property
    def uid(self):
        """Return unique id."""
        return f"{self.organisation_id}_{self.account_id}"


class ApiError(exceptions.HomeAssistantError):
    """Error to indicate api error."""


class ApiAuthError(exceptions.HomeAssistantError):
    """Error to indicate auth error."""
