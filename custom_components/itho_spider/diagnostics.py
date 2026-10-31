"""Downloadable diagnostics without serial paths or raw neighbour traffic."""

from homeassistant.components.diagnostics import async_redact_data


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    return {
        "entry": async_redact_data(dict(entry.data), {"port", "gateway_id", "spider_id", "name"}),
        "options": dict(entry.options),
        "controller": entry.runtime_data.controller.diagnostics(),
    }
