"""Constants for the integration."""

import datetime
from enum import IntEnum
from typing import Any, Final

DOMAIN: Final = "kvartac"

CONF_ACC_ID: Final = "acc_id"
CONF_ORG_ID: Final = "org_id"
CONF_PASSWD: Final = "passwd"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_DIAGNOSTIC_SENSORS: Final = "diagnostic_sensors"
CONF_PREV_DATE_SENSOR: Final = "prev_date_sensor"

DEFAULT_UPDATE_INTERVAL: Final = datetime.timedelta(hours=12)

SERVICE_UPDATE_VALUE_CODE: Final = "update_value"

MESSAGE_SUCCESS: Final = "Показания переданы"


class ErrorCode(IntEnum):
    """Codes of service action results."""

    SUCCESS = 0
    CONNECTION = -1
    UNAVAILABLE = -2
    VALUE = -3
    API = -7
    AUTH = -8


def make_result(code: ErrorCode, message: str, **extra: Any) -> dict[str, Any]:
    """Return a service action result."""
    return {"code": int(code), "message": message, **extra}
