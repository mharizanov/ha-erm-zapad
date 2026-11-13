"""Config and options flow for the ERM Zapad outage check."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    DateSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

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
    DEFAULT_SENSOR_ID,
    DEFAULT_TITLE,
    DOMAIN,
    NAME,
)
from .parser import KEYWORD_PLACEHOLDER


def _form_defaults() -> dict[str, Any]:
    """Defaults for a fresh form."""
    return {
        CONF_KEYWORD: "",
        CONF_BASE_DATE: DEFAULT_BASE_DATE,
        CONF_BASE_DOC_ID: DEFAULT_BASE_DOC_ID,
        CONF_ENDPOINT: DEFAULT_ENDPOINT,
        CONF_REGEX: DEFAULT_REGEX,
        CONF_NOTIFICATION_TITLE: DEFAULT_TITLE,
        CONF_SENSOR_ENTITY_ID: DEFAULT_SENSOR_ID,
        CONF_CHECK_TIME: DEFAULT_CHECK_TIME,
        CONF_DRIFT_WINDOW: DEFAULT_DRIFT_WINDOW,
        CONF_NOTIFY_SERVICES: [],
    }


def _notify_options(hass: HomeAssistant, current: list[str]) -> list[str]:
    services = hass.services.async_services().get("notify", {})
    opts = sorted(f"notify.{name}" for name in services)
    for c in current or []:
        if c not in opts:
            opts.append(c)
    return opts


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce selector values into JSON-serialisable, typed config."""
    out = dict(data)
    out[CONF_KEYWORD] = str(out.get(CONF_KEYWORD, "")).strip()
    if out.get(CONF_BASE_DOC_ID) is not None:
        out[CONF_BASE_DOC_ID] = int(out[CONF_BASE_DOC_ID])
    if out.get(CONF_DRIFT_WINDOW) is not None:
        out[CONF_DRIFT_WINDOW] = int(out[CONF_DRIFT_WINDOW])
    bd = out.get(CONF_BASE_DATE)
    if hasattr(bd, "isoformat"):
        out[CONF_BASE_DATE] = bd.isoformat()
    ns = out.get(CONF_NOTIFY_SERVICES)
    if isinstance(ns, str):
        out[CONF_NOTIFY_SERVICES] = [ns]
    elif ns is None:
        out[CONF_NOTIFY_SERVICES] = []
    return out


def _validate(data: dict[str, Any]) -> dict[str, str]:
    """Return form errors keyed by field."""
    import re

    errors: dict[str, str] = {}
    if not data.get(CONF_KEYWORD):
        errors[CONF_KEYWORD] = "keyword_required"
    regex = data.get(CONF_REGEX) or DEFAULT_REGEX
    try:
        re.compile(regex.replace(KEYWORD_PLACEHOLDER, "x"))
    except re.error:
        errors[CONF_REGEX] = "invalid_regex"
    return errors


def _build_schema(hass: HomeAssistant, defaults: dict[str, Any]) -> vol.Schema:
    current = defaults.get(CONF_NOTIFY_SERVICES) or []
    notify_opts = _notify_options(hass, current)
    return vol.Schema(
        {
            vol.Required(
                CONF_KEYWORD, default=defaults.get(CONF_KEYWORD, "")
            ): TextSelector(),
            vol.Optional(
                CONF_NOTIFY_SERVICES, default=current
            ): SelectSelector(
                SelectSelectorConfig(
                    options=notify_opts,
                    multiple=True,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_CHECK_TIME,
                default=defaults.get(CONF_CHECK_TIME, DEFAULT_CHECK_TIME),
            ): TimeSelector(),
            vol.Required(
                CONF_BASE_DATE,
                default=defaults.get(CONF_BASE_DATE, DEFAULT_BASE_DATE),
            ): DateSelector(),
            vol.Required(
                CONF_BASE_DOC_ID,
                default=defaults.get(CONF_BASE_DOC_ID, DEFAULT_BASE_DOC_ID),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=10000000, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_DRIFT_WINDOW,
                default=defaults.get(CONF_DRIFT_WINDOW, DEFAULT_DRIFT_WINDOW),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=10, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_NOTIFICATION_TITLE,
                default=defaults.get(CONF_NOTIFICATION_TITLE, DEFAULT_TITLE),
            ): TextSelector(),
            vol.Optional(
                CONF_ENDPOINT, default=defaults.get(CONF_ENDPOINT, DEFAULT_ENDPOINT)
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            vol.Optional(
                CONF_REGEX, default=defaults.get(CONF_REGEX, DEFAULT_REGEX)
            ): TextSelector(),
            vol.Optional(
                CONF_SENSOR_ENTITY_ID,
                default=defaults.get(CONF_SENSOR_ENTITY_ID, DEFAULT_SENSOR_ID),
            ): TextSelector(),
        }
    )


class ErmZapadConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the outage check (single instance)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        defaults = _form_defaults()
        if user_input is not None:
            data = _normalize(user_input)
            errors = _validate(data)
            if not errors:
                return self.async_create_entry(title=NAME, data=data)
            defaults.update(data)
        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(self.hass, defaults),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ErmZapadOptionsFlow()


class ErmZapadOptionsFlow(OptionsFlow):
    """Edit any setting after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = {**_form_defaults(), **self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            data = _normalize(user_input)
            errors = _validate(data)
            if not errors:
                return self.async_create_entry(title="", data=data)
            defaults.update(data)
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(self.hass, defaults),
            errors=errors,
        )
