"""Exercise the real HTTP form serializer, not only the flow manager."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.config import config_entries as config_entries_api
from homeassistant.const import CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.itho_spider.const import (
    CONF_ENABLE_CONTROL,
    CONF_GATEWAY_ID,
    CONF_SPIDER_ID,
    CONF_WAIT_FOR_WAKEUP,
    DOMAIN,
)

GATEWAY = "18:123456"
SPIDER = "21:123456"

pytestmark = pytest.mark.asyncio


async def test_http_config_and_options_forms_serialize(
    hass: HomeAssistant, hass_client, enable_custom_integrations: None
) -> None:
    """A browser can open, correct, submit, and reopen the options form."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "websocket_api", {})
    assert config_entries_api.async_setup(hass)
    client = await hass_client()
    probe = AsyncMock(return_value=GATEWAY)

    with (
        patch("custom_components.itho_spider.config_flow.async_probe_port", probe),
        patch("custom_components.itho_spider.async_setup_entry", return_value=True),
    ):
        response = await client.post(
            "/api/config/config_entries/flow",
            json={"handler": DOMAIN, "show_advanced_options": False},
        )
        assert response.status == 200, await response.text()
        form = await response.json()
        assert form["type"] == "form"
        assert form["step_id"] == "user"
        fields = {field["name"]: field for field in form["data_schema"]}
        assert set(fields) == {
            CONF_PORT,
            CONF_GATEWAY_ID,
            CONF_SPIDER_ID,
            CONF_NAME,
            CONF_ENABLE_CONTROL,
            CONF_WAIT_FOR_WAKEUP,
        }
        for key in (CONF_PORT, CONF_GATEWAY_ID, CONF_SPIDER_ID, CONF_NAME):
            assert "text" in fields[key]["selector"]
        assert "boolean" in fields[CONF_ENABLE_CONTROL]["selector"]
        assert fields[CONF_ENABLE_CONTROL]["default"] is True
        assert "default" not in fields[CONF_GATEWAY_ID]
        assert "default" not in fields[CONF_SPIDER_ID]
        assert fields[CONF_NAME]["default"] == "Itho Spider"
        probe.assert_not_awaited()

        inputs = {
            CONF_PORT: "socket://localhost:1234",
            CONF_GATEWAY_ID: GATEWAY,
            CONF_SPIDER_ID: SPIDER,
            CONF_NAME: "Test room A",
            CONF_ENABLE_CONTROL: False,
        }
        response = await client.post(
            f"/api/config/config_entries/flow/{form['flow_id']}", json=inputs
        )
        assert response.status == 200, await response.text()
        invalid_form = await response.json()
        assert invalid_form["type"] == "form"
        assert invalid_form["errors"] == {CONF_PORT: "invalid_port"}
        probe.assert_not_awaited()

        inputs[CONF_PORT] = "/dev/ttyACM0"
        response = await client.post(
            f"/api/config/config_entries/flow/{form['flow_id']}", json=inputs
        )
        assert response.status == 200, await response.text()
        association = await response.json()
        assert association["type"] == "menu"
        response = await client.post(
            f"/api/config/config_entries/flow/{form['flow_id']}",
            json={"next_step_id": "save_later"},
        )
        created = await response.json()
        assert created["type"] == "create_entry"
        await hass.async_block_till_done()
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        assert entry.options == {CONF_ENABLE_CONTROL: False, CONF_WAIT_FOR_WAKEUP: False}
        probe.assert_awaited_once_with("/dev/ttyACM0")

        response = await client.post(
            "/api/config/config_entries/options/flow", json={"handler": entry.entry_id}
        )
        assert response.status == 200, await response.text()
        menu = await response.json()
        assert menu["type"] == "menu"
        response = await client.post(
            f"/api/config/config_entries/options/flow/{menu['flow_id']}",
            json={"next_step_id": "settings"},
        )
        options = await response.json()
        assert options["type"] == "form"
        fields = {field["name"]: field for field in options["data_schema"]}
        assert "boolean" in fields[CONF_ENABLE_CONTROL]["selector"]
        assert fields[CONF_ENABLE_CONTROL]["default"] is False

        hass.config_entries.options.async_abort(options["flow_id"])
        response = await client.post(
            "/api/config/config_entries/options/flow", json={"handler": entry.entry_id}
        )
        removal = await response.json()
        url = f"/api/config/config_entries/options/flow/{removal['flow_id']}"
        for step in ("remove", "remove_ha"):
            response = await client.post(url, json={"next_step_id": step})
            assert response.status == 200, await response.text()
        form = await response.json()
        assert form["data_schema"][0]["default"] is False
        response = await client.post(url, json={"confirm": False})
        assert (await response.json())["errors"] == {"base": "confirmation_required"}
        assert hass.config_entries.async_get_entry(entry.entry_id) is entry
        with patch("custom_components.itho_spider.async_unload_entry", return_value=True):
            response = await client.post(url, json={"confirm": True})
        assert response.status == 200, await response.text()
        removed = await response.json()
        assert removed["type"] == "abort" and removed["reason"] == "removed"
        assert hass.config_entries.async_get_entry(entry.entry_id) is None
