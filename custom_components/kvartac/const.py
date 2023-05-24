"""Constants for the integration."""
import datetime
from typing import Final


DOMAIN: Final = "kvartac"

CONF_ACC_ID: Final = "acc_id"
CONF_ORG_ID: Final = "org_id"
CONF_PASSWD: Final = "passwd"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_DIAGNOSTIC_SENSORS: Final = "diagnostic_sensors"
CONF_PREV_DATE_SENSOR: Final = "prev_date_sensor"

DEFAULT_UPDATE_INTERVAL: Final = datetime.timedelta(hours=12)

SERVICE_UPDATE_VALUE_CODE: Final = "update_value"
