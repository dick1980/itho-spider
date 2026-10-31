"""Guided lifecycle through real HA flows, registries and shared simulated USB."""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_NAME, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_integration import GATEWAY, PORT, SPIDER, STATUS_21, FakeTransport, packet

from custom_components.itho_spider.binding import address_hex
from custom_components.itho_spider.const import (
    CONF_ENABLE_CONTROL,
    CONF_GATEWAY_ID,
    CONF_SPIDER_ID,
    CONF_WAIT_FOR_WAKEUP,
    DOMAIN,
)
from custom_components.itho_spider.controller import ControlError

UPSTAIRS = "21:123457"
pytestmark = pytest.mark.asyncio


@pytest.fixture
async def usb(hass):
    buses = []

    def factory(*args, **kwargs):
        bus = FakeTransport(*args, **kwargs)
        buses.append(bus)
        return bus

    with (
        patch("custom_components.itho_spider.shared_gateway.GatewayTransport", factory),
        patch("custom_components.itho_spider.config_flow.async_probe_port", return_value=GATEWAY),
    ):
        yield buses
        for flow in hass.config_entries.flow.async_progress():
            if flow["handler"] == DOMAIN:
                hass.config_entries.flow.async_abort(flow["flow_id"])
        for flow in hass.config_entries.options.async_progress():
            hass.config_entries.options.async_abort(flow["flow_id"])
        for entry in hass.config_entries.async_entries(DOMAIN):
            await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def add(hass, spider=SPIDER):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title=spider,
        unique_id=spider,
        data={CONF_PORT: PORT, CONF_GATEWAY_ID: GATEWAY, CONF_SPIDER_ID: spider, CONF_NAME: spider},
        options={CONF_ENABLE_CONTROL: True, CONF_WAIT_FOR_WAKEUP: spider == UPSTAIRS},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def ready(entry):
    c = entry.runtime_data.controller
    for line in [
        packet("3110", "00000010", src=c.spider_id),
        packet("01FF", STATUS_21, src=c.spider_id, dst=GATEWAY),
    ]:
        await c.async_process_line(line)
    assert c.control_ready
    return c


async def options(hass, entry, *steps):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    for step in steps:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": step}
        )
    return result


async def test_remove_owner_preserves_other_spider_and_gateway_device(hass, usb):
    first, second = await add(hass), await add(hass, UPSTAIRS)
    await ready(first)
    other = await ready(second)
    registry = dr.async_get(hass)
    gateway = registry.async_get_devices(identifiers={(DOMAIN, GATEWAY)})[0]
    assert gateway.config_entry_id == first.entry_id
    other_entity = er.async_get(hass).async_get_entity_id("climate", DOMAIN, f"{UPSTAIRS}_climate")
    result = await options(hass, first, "remove", "remove_ha")
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"confirm": False}
    )
    assert result["errors"] == {"base": "confirmation_required"}
    assert hass.config_entries.async_get_entry(first.entry_id)
    before = list(usb[0].sent)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"confirm": True})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "removed"
    assert hass.config_entries.async_get_entry(first.entry_id) is None
    assert usb[0].sent == before and usb[0].close_count == 0
    assert registry.async_get(gateway.id).config_entry_id == second.entry_id
    assert other.control_ready and other.transport.is_connected
    assert hass.states.get(other_entity).attributes["temperature"] == 21
    await other.async_process_line(packet("01FF", STATUS_21, verb="RQ", src=UPSTAIRS, dst=GATEWAY))
    assert "RP ---" in usb[0].sent[-1]
    await hass.config_entries.async_remove(second.entry_id)
    assert usb[0].close_count == 1


async def test_cancel_physical_removal_resumes_only_after_fresh_bound_status(hass, usb):
    entry = await add(hass)
    c = await ready(entry)
    result = await options(hass, entry, "remove", "unpair_prepare")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["step_id"] == "unpair_confirm"
    assert not c.control_ready
    with pytest.raises(ControlError):
        await c.async_set_temperature(21.5)
    with pytest.raises(ControlError):
        c.arm_pairing()
    await c.async_process_line(packet("01FF", STATUS_21, verb="RQ", dst=GATEWAY))
    await c.async_process_line(packet("22C9", "00083408FC01", verb="W", dst=GATEWAY))
    assert not usb[0].sent
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"confirm": False}
    )
    assert result["errors"] == {"base": "confirmation_required"}
    hass.config_entries.options.async_abort(result["flow_id"])
    assert hass.config_entries.async_get_entry(entry.entry_id)
    assert not c.diagnostics()["removal_in_progress"] and not c.control_ready
    await c.async_process_line(packet("01FF", STATUS_21, verb="RQ", dst=GATEWAY))
    assert c.control_ready
    assert len(usb[0].sent) == 1


async def test_physical_removal_needs_two_explicit_confirmations(hass, usb):
    entry = await add(hass)
    await ready(entry)
    result = await options(hass, entry, "remove", "unpair_prepare")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["step_id"] == "unpair_confirm"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"confirm": True})
    assert result["step_id"] == "remove_confirm"
    assert hass.config_entries.async_get_entry(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"confirm": True})
    assert result["reason"] == "removed"
    assert not usb[0].sent and usb[0].closed


async def test_expired_removal_cannot_delete_entry(hass, usb):
    entry = await add(hass)
    c = await ready(entry)
    result = await options(hass, entry, "remove", "unpair_prepare")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    flow = hass.config_entries.options._progress[result["flow_id"]]
    flow._removal_token = c._removal_until = 1
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"confirm": True})
    assert result["reason"] == "removal_expired"
    assert hass.config_entries.async_get_entry(entry.entry_id)
    assert not c.diagnostics()["removal_in_progress"]
    assert not usb[0].sent


async def test_existing_pair_check_does_not_reload_or_change_identity(hass, usb):
    entry = await add(hass)
    c = await ready(entry)
    entity = er.async_get(hass).async_get_entity_id("climate", DOMAIN, f"{SPIDER}_climate")
    device_id = er.async_get(hass).async_get(entity).device_id
    original_options = dict(entry.options)
    result = await options(hass, entry, "pair_prepare")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair_result"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"confirm": True})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.runtime_data.controller is c
    assert entry.options == original_options and entry.version == 2
    assert er.async_get(hass).async_get(entity).device_id == device_id
    assert not usb[0].sent and usb[0].close_count == 0


async def start_new_pair(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={
            CONF_PORT: PORT,
            CONF_GATEWAY_ID: GATEWAY,
            CONF_SPIDER_ID: UPSTAIRS,
            CONF_NAME: "Test room B test",
            CONF_ENABLE_CONTROL: True,
            CONF_WAIT_FOR_WAKEUP: True,
        },
    )
    assert result["step_id"] == "association"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "pair_prepare"}
    )
    assert result["step_id"] == "pair_prepare"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    return result, hass.config_entries.flow._progress[result["flow_id"]]


async def test_new_pair_confirmation_creates_correct_entry_with_shared_usb(hass, usb):
    first = await add(hass)
    await ready(first)
    result, flow = await start_new_pair(hass)
    c = flow._pair_controller
    assert len(usb) == 1 and usb[0].connect_count == 1
    own = address_hex(UPSTAIRS)
    offer = "".join(prefix + own for prefix in ["0022C9", "0022F1", "00000E", "0110E0", "001FC9"])
    await c.async_process_line(packet("1FC9", offer, src=UPSTAIRS))
    await c.async_process_line(packet("1FC9", "00", src=UPSTAIRS, dst=GATEWAY))
    await flow._pair_task
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair_result"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"confirm": True})
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.unique_id == UPSTAIRS and entry.options[CONF_WAIT_FOR_WAKEUP]
    assert entry.runtime_data.controller.transport.is_connected
    assert first.runtime_data.controller.control_ready
    assert usb[0].close_count == 0
    assert usb[0].sent == [f"W --- {GATEWAY} {UPSTAIRS} --:------ 1FC9 006 0001FF49E240"]


async def test_cancel_new_pair_releases_only_temporary_usb_client(hass, usb):
    first = await add(hass)
    result, flow = await start_new_pair(hass)
    c = flow._pair_controller
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert c.pairing_status == "cancelled"
    assert not c.transport.is_connected
    assert first.runtime_data.controller.transport.is_connected
    assert usb[0].close_count == 0 and not usb[0].sent
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_pair_timeout_can_retry_or_save_without_claiming_pairing(hass, usb):
    with patch("custom_components.itho_spider.pairing_flow.PAIRING_TIMEOUT", 0.01):
        result, flow = await start_new_pair(hass)
        await flow._pair_task
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "pair_failed"
    assert not hass.config_entries.async_entries(DOMAIN)
    assert usb[0].closed and not usb[0].sent
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "save_later"}
    )
    await hass.async_block_till_done()
    assert result["result"].runtime_data.controller.diagnostics()["bound_status_seen"] is False


async def test_unpair_does_not_interrupt_pending_temperature_command(hass, usb):
    entry = await add(hass, UPSTAIRS)
    c = await ready(entry)
    await c.async_set_temperature(21.5)
    await asyncio.sleep(0)
    result = await options(hass, entry, "remove", "unpair_prepare")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "operation_busy"}
    assert c.pending_temperature == 21.5
    assert not c.diagnostics()["removal_in_progress"]


async def test_pair_retry_owns_new_window_and_releases_usb_on_cancel(hass, usb):
    with patch("custom_components.itho_spider.pairing_flow.PAIRING_TIMEOUT", 0.01):
        result, flow = await start_new_pair(hass)
        first = flow._pair_controller
        await flow._pair_task
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["step_id"] == "pair_failed"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "pair_prepare"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    second = flow._pair_controller
    assert second is not first and second.pairing_status == "waiting_for_offer"
    assert not first.transport.is_connected and second.transport.is_connected
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert second.pairing_status == "cancelled" and not second.transport.is_connected
    assert not hass.config_entries.async_entries(DOMAIN)
    assert not usb[0].sent
