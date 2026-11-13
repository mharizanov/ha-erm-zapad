"""Constants for the ERM Zapad outage check."""
from __future__ import annotations

from .parser import DEFAULT_REGEX  # noqa: F401  (re-exported)

DOMAIN = "erm_zapad"
NAME = "ERM Zapad Outage Check"

# Config keys
CONF_ENDPOINT = "endpoint"
CONF_BASE_DATE = "base_date"
CONF_BASE_DOC_ID = "base_doc_id"
CONF_KEYWORD = "keyword"
CONF_REGEX = "regex"
CONF_NOTIFICATION_TITLE = "notification_title"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_SENSOR_ENTITY_ID = "sensor_entity_id"
CONF_CHECK_TIME = "check_time"
CONF_DRIFT_WINDOW = "drift_window"

# Defaults
DEFAULT_ENDPOINT = "https://info.ermzapad.bg/webint/vok/avplan.php"
DEFAULT_TITLE = "Електрохолд планирани спирания"
DEFAULT_SENSOR_ID = "sensor.erm_zapad_next_outage"
DEFAULT_CHECK_TIME = "21:15:00"
DEFAULT_DRIFT_WINDOW = 3

# Calibration anchor. ERM Zapad numbers its daily PDFs with a doc_id that grows by
# one per day. On day D the check expects doc_id BASE_DOC_ID + (D - BASE_DATE) to
# be the PDF for D + 1 and scans ±drift_window around it. Checked against every
# PDF from 18.11.2025 to 10.11.2026 and for 13-14.11.2026: one gap (no PDF for 25.12.2025), drift 0 since
# then. Change the anchor only if the drift approaches drift_window.
DEFAULT_BASE_DATE = "2025-11-18"
DEFAULT_BASE_DOC_ID = 1481

# Minutes after the daily check at which the freshness watchdog runs.
DEFAULT_WATCHDOG_DELAY_MIN = 10

# A fetch around 21:00, when the next-day PDF is being rewritten, can fail for the
# expected doc_id only. Retry the whole scan before alerting. Keep
# RETRIES * DELAY below the watchdog delay so checked_at stays fresh.
DEFAULT_RETRIES = 2
DEFAULT_RETRY_DELAY_MIN = 4

# Served by the integration itself (see async_setup), used as entity_picture.
LOGO_URL = "/erm_zapad/icon.png"
