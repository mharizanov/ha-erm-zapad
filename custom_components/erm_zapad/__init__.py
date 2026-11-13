"""ERM Zapad outage check.

Every evening the integration downloads the next day's planned-outage PDF that
ERM Zapad (Electrohold) publishes for western Bulgaria, looks for a configured
keyword (a settlement or district name) and notifies when it is listed.

doc_id self-calibration: each daily PDF has a doc_id that grows by one per day,
and its header carries the date the outages apply to ('Планирани прекъсвания за
DD.MM.YYYY'). The expected doc_id is computed from a base anchor plus the days
since then; the PDF date is checked against tomorrow, and on a mismatch the
neighbouring doc_ids (±drift_window) are tried. If none matches, the sensor goes
to 'calibration error' and a failure notification is sent.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BASE_DATE,
    CONF_BASE_DOC_ID,
    CONF_CHECK_TIME,
    CONF_DRIFT_WINDOW,
    CONF_ENDPOINT,
    CONF_KEYWORD,
    CONF_NOTIFICATION_TITLE,
    CONF_NOTIFY_SERVICES,
    CONF_REGEX,
    CONF_SENSOR_ENTITY_ID,
    DEFAULT_BASE_DATE,
    DEFAULT_BASE_DOC_ID,
    DEFAULT_CHECK_TIME,
    DEFAULT_DRIFT_WINDOW,
    DEFAULT_ENDPOINT,
    DEFAULT_REGEX,
    DEFAULT_RETRIES,
    DEFAULT_RETRY_DELAY_MIN,
    DEFAULT_SENSOR_ID,
    DEFAULT_TITLE,
    DEFAULT_WATCHDOG_DELAY_MIN,
    DOMAIN,
    LOGO_URL,
)
from .parser import (
    compile_outage_regex,
    extract_pdf_date,
    find_outages,
    keyword_in_text,
    pdf_to_text,
)

_LOGGER = logging.getLogger(__name__)

# The PDFs follow the operator's local calendar day.
SOFIA = ZoneInfo("Europe/Sofia")

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Defaults for keys a config entry may omit.
_OPTIONAL_DEFAULTS = {
    CONF_ENDPOINT: DEFAULT_ENDPOINT,
    CONF_BASE_DATE: DEFAULT_BASE_DATE,
    CONF_BASE_DOC_ID: DEFAULT_BASE_DOC_ID,
    CONF_REGEX: DEFAULT_REGEX,
    CONF_NOTIFICATION_TITLE: DEFAULT_TITLE,
    CONF_SENSOR_ENTITY_ID: DEFAULT_SENSOR_ID,
    CONF_CHECK_TIME: DEFAULT_CHECK_TIME,
    CONF_DRIFT_WINDOW: DEFAULT_DRIFT_WINDOW,
    CONF_NOTIFY_SERVICES: [],
}

_ICON_OK = "mdi:transmission-tower"
_ICON_ALERT = "mdi:transmission-tower-off"


def _merged_conf(entry: ConfigEntry) -> dict:
    """Effective config = defaults < entry.data < entry.options (empty values ignored)."""
    conf = dict(_OPTIONAL_DEFAULTS)
    for source in (entry.data, entry.options):
        for key, value in source.items():
            if value not in (None, ""):
                conf[key] = value
    return conf


def _parse_hms(value: str) -> tuple[int, int, int]:
    parts = [int(p) for p in str(value).split(":")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0] % 24, parts[1] % 60, parts[2] % 60


def _add_minutes(h: int, m: int, s: int, minutes: int) -> tuple[int, int, int]:
    total = (h * 60 + m + minutes) % (24 * 60)
    return total // 60, total % 60, s


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled icon so the sensor can use it as entity_picture."""
    if getattr(hass, "http", None) is not None:
        from homeassistant.components.http import StaticPathConfig

        icon = Path(__file__).parent / "brand" / "icon.png"
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(LOGO_URL, str(icon), True)]
            )
        except RuntimeError:
            # Already registered (integration reloaded without a restart).
            pass
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    conf = _merged_conf(entry)
    hass.data.setdefault(DOMAIN, {})

    sensor_id = conf[CONF_SENSOR_ENTITY_ID]
    if hass.states.get(sensor_id) is None:
        hass.states.async_set(
            sensor_id,
            "unknown",
            {
                "friendly_name": "ERM Zapad next outage",
                "icon": _ICON_ALERT,
                "entity_picture": LOGO_URL,
            },
        )

    # Manual trigger (registered once, runs every entry).
    if not hass.services.has_service(DOMAIN, "check"):

        async def _handle_check(call: ServiceCall) -> None:
            for e in hass.config_entries.async_entries(DOMAIN):
                await _check(hass, _merged_conf(e))

        hass.services.async_register(DOMAIN, "check", _handle_check)

    # Daily check + freshness watchdog at the configured time.
    h, m, s = _parse_hms(conf[CONF_CHECK_TIME])
    wh, wm, ws = _add_minutes(h, m, s, DEFAULT_WATCHDOG_DELAY_MIN)

    @callback
    def _scheduled_check(_now) -> None:
        hass.async_create_task(_check(hass, _merged_conf(entry)))

    @callback
    def _scheduled_watchdog(_now) -> None:
        hass.async_create_task(_watchdog(hass, _merged_conf(entry)))

    entry.async_on_unload(
        async_track_time_change(hass, _scheduled_check, hour=h, minute=m, second=s)
    )
    entry.async_on_unload(
        async_track_time_change(hass, _scheduled_watchdog, hour=wh, minute=wm, second=ws)
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    hass.data[DOMAIN][entry.entry_id] = conf
    _LOGGER.info(
        "erm_zapad set up (sensor=%s, check_time=%02d:%02d:%02d, drift=±%s)",
        sensor_id, h, m, s, conf[CONF_DRIFT_WINDOW],
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry (trackers and listeners go via async_on_unload)."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if not remaining and hass.services.has_service(DOMAIN, "check"):
        hass.services.async_remove(DOMAIN, "check")
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


async def _fetch_pdf(session, endpoint: str, doc_id: int) -> bytes:
    form = aiohttp.FormData()
    form.add_field("action", "showdocid")
    form.add_field("doc_id", str(doc_id))
    timeout = aiohttp.ClientTimeout(total=30)
    async with session.post(endpoint, data=form, timeout=timeout) as resp:
        resp.raise_for_status()
        return await resp.read()


async def _try_doc_id(hass, session, endpoint, doc_id):
    """Return (raw_bytes, text, pdf_date) on success, or a failure-reason str."""
    try:
        raw = await _fetch_pdf(session, endpoint, doc_id)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("erm_zapad fetch failed for doc_id=%s: %s", doc_id, exc)
        return f"fetch failed: {type(exc).__name__}: {exc}"[:200]
    try:
        text = await hass.async_add_executor_job(pdf_to_text, raw)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("erm_zapad PDF parse failed for doc_id=%s: %s", doc_id, exc)
        return f"parse failed ({len(raw)} B): {type(exc).__name__}: {exc}"[:200]
    return raw, text, extract_pdf_date(text)


async def _notify(hass, notify_services, title, message) -> None:
    for ns in notify_services:
        if not str(ns).startswith("notify."):
            _LOGGER.warning("erm_zapad: ignoring unrecognised notify service %r", ns)
            continue
        domain, service = ns.split(".", 1)
        try:
            await hass.services.async_call(
                domain, service, {"title": title, "message": message}, blocking=False
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("erm_zapad notify %s failed: %s", ns, exc)


async def _watchdog(hass: HomeAssistant, conf: dict) -> None:
    """Alert if the daily check did not refresh the sensor's checked_at."""
    sensor_id = conf[CONF_SENSOR_ENTITY_ID]
    st = hass.states.get(sensor_id)
    checked_at = st.attributes.get("checked_at") if st else None
    stale = True
    if checked_at:
        try:
            ts = _dt.datetime.fromisoformat(checked_at)
            stale = (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds() > 15 * 60
        except ValueError:
            stale = True
    if not stale:
        return
    _LOGGER.warning("erm_zapad watchdog: daily check appears not to have run")
    await _notify(
        hass,
        conf[CONF_NOTIFY_SERVICES],
        "⚠ ERM Zapad check did not run",
        (
            f"The daily ERM Zapad outage check did not run on schedule. "
            f"Last checked: {checked_at or 'never'}. "
            f"Sensor state: {st.state if st else 'missing'}."
        ),
    )


async def _check(hass: HomeAssistant, conf: dict) -> None:
    sensor_id = conf[CONF_SENSOR_ENTITY_ID]
    endpoint = conf[CONF_ENDPOINT]
    base_date = conf[CONF_BASE_DATE]
    if isinstance(base_date, str):
        base_date = _dt.date.fromisoformat(base_date)
    base_doc_id = int(conf[CONF_BASE_DOC_ID])
    keyword = str(conf[CONF_KEYWORD]).strip()
    pattern = compile_outage_regex(conf[CONF_REGEX], keyword)
    title = conf[CONF_NOTIFICATION_TITLE]
    notify_services = conf[CONF_NOTIFY_SERVICES]
    drift_window = int(conf.get(CONF_DRIFT_WINDOW, DEFAULT_DRIFT_WINDOW))

    today = _dt.datetime.now(SOFIA).date()
    # The check runs in the evening; the PDF lists the NEXT day's outages.
    expected_pdf_date = today + _dt.timedelta(days=1)
    initial_doc_id = base_doc_id + (today - base_date).days

    base_attrs = {
        "friendly_name": "ERM Zapad next outage",
        "entity_picture": LOGO_URL,
        "keyword": keyword,
        "checked_at": _now_iso(),
        "expected_pdf_date": expected_pdf_date.isoformat(),
        "initial_doc_id": initial_doc_id,
    }

    session = async_get_clientsession(hass)

    # Initial doc_id first, then ±1..±drift_window by proximity.
    candidates = [0]
    for d in range(1, drift_window + 1):
        candidates.extend([d, -d])

    used = None
    tried: list[tuple[int, int, str]] = []
    for attempt in range(DEFAULT_RETRIES + 1):
        if attempt:
            await asyncio.sleep(DEFAULT_RETRY_DELAY_MIN * 60)
            base_attrs["checked_at"] = _now_iso()
        base_attrs["attempt"] = attempt + 1
        tried = []
        for drift in candidates:
            doc_id = initial_doc_id + drift
            result = await _try_doc_id(hass, session, endpoint, doc_id)
            if isinstance(result, str):
                tried.append((drift, doc_id, result))
                continue
            raw, text, pdf_date = result
            tried.append((drift, doc_id, pdf_date.isoformat() if pdf_date else "no-date-in-pdf"))
            if pdf_date == expected_pdf_date:
                used = (drift, doc_id, pdf_date, raw, text)
                break
        if used is not None or attempt == DEFAULT_RETRIES:
            break
        # Interim state keeps checked_at fresh for the watchdog and shows the retry.
        hass.states.async_set(
            sensor_id,
            "retrying",
            {
                **base_attrs,
                "icon": _ICON_ALERT,
                "tried": [{"drift": d, "doc_id": i, "pdf_date": p} for d, i, p in tried],
            },
        )
        _LOGGER.info(
            "erm_zapad attempt %s/%s failed (%s); retrying in %s min",
            attempt + 1, DEFAULT_RETRIES + 1, tried[0][2], DEFAULT_RETRY_DELAY_MIN,
        )

    if used is None:
        hass.states.async_set(
            sensor_id,
            "calibration error",
            {
                **base_attrs,
                "icon": _ICON_ALERT,
                "tried": [{"drift": d, "doc_id": i, "pdf_date": p} for d, i, p in tried],
            },
        )
        _LOGGER.warning(
            "erm_zapad calibration failed after %s attempts; expected pdf_date=%s; tried %s",
            DEFAULT_RETRIES + 1,
            expected_pdf_date,
            [{"doc_id": i, "pdf_date": p} for _, i, p in tried],
        )
        await _notify(
            hass,
            notify_services,
            "⚠ ERM Zapad check failed",
            (
                f"Could not retrieve tomorrow's ({expected_pdf_date.isoformat()}) outage "
                f"schedule: no PDF around doc_id {initial_doc_id} matched the expected "
                f"date. The site may be down or the documents renumbered. Check manually."
            ),
        )
        return

    drift, doc_id, pdf_date, raw, text = used
    if drift != 0:
        _LOGGER.warning(
            "erm_zapad doc_id drift: initial=%s, working=%s (drift=%+d, pdf_date=%s)",
            initial_doc_id, doc_id, drift, pdf_date,
        )

    common_attrs = {
        **base_attrs,
        "doc_id": doc_id,
        "doc_id_drift": drift,
        "pdf_date": pdf_date.isoformat(),
        "bytes": len(raw),
        "pdf_chars": len(text),
    }

    if not keyword_in_text(keyword, text):
        hass.states.async_set(sensor_id, "no outage", {**common_attrs, "icon": _ICON_OK})
        hass.bus.async_fire(f"{DOMAIN}_checked", {"match": False, "doc_id": doc_id})
        return

    outages = find_outages(pattern, text)
    if not outages:
        hass.states.async_set(
            sensor_id,
            "keyword without regex match",
            {**common_attrs, "icon": _ICON_ALERT},
        )
        hass.bus.async_fire(f"{DOMAIN}_checked", {"match": "partial", "doc_id": doc_id})
        await _notify(
            hass,
            notify_services,
            "⚠ ERM Zapad: outage found but not parsed",
            (
                f"'{keyword}' appears in tomorrow's ({pdf_date.isoformat()}) outage "
                f"schedule (doc_id {doc_id}), but the outage time could not be parsed. "
                f"There is probably a real outage; check the schedule manually."
            ),
        )
        return

    first = outages[0]
    hass.states.async_set(
        sensor_id,
        first.line[:255],
        {
            **common_attrs,
            "icon": _ICON_ALERT,
            "outage_start": first.start,
            "outage_end": first.end,
            "full_match": first.line,
            "outages": [
                {"area": o.area, "start": o.start, "end": o.end} for o in outages
            ],
        },
    )

    await _notify(hass, notify_services, title, "\n".join(o.line for o in outages))

    hass.bus.async_fire(
        f"{DOMAIN}_checked",
        {
            "match": True,
            "match_line": first.line,
            "outage_start": first.start,
            "outage_end": first.end,
            "outages": [o.line for o in outages],
            "doc_id": doc_id,
        },
    )
