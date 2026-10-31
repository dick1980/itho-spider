"""Two real controllers share one USB connection and cannot address the BDR91."""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_NAME, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_integration import GATEWAY, PORT, SPIDER, STATUS_21, FakeTransport, packet

from custom_components.itho_spider import async_migrate_entry
from custom_components.itho_spider.binding import address_hex
from custom_components.itho_spider.const import (
    CONF_ENABLE_CONTROL,
    CONF_GATEWAY_ID,
    CONF_SPIDER_ID,
    DOMAIN,
)
from custom_components.itho_spider.controller import ControlError, SpiderController
from custom_components.itho_spider.shared_gateway import SharedGateway

UPSTAIRS = "21:123457"
RELAY = "13:123456"
pytestmark = pytest.mark.asyncio


async def test_two_entries_share_usb_route_confirmations_and_survive_unload(hass):
    buses = []

    def factory(*args, **kwargs):
        bus = FakeTransport(*args, **kwargs)
        buses.append(bus)
        return bus

    entries = []
    with patch("custom_components.itho_spider.shared_gateway.GatewayTransport", factory):
        try:
            for spider, name in [(SPIDER, "Test room A"), (UPSTAIRS, "Test room B")]:
                entry = MockConfigEntry(
                    domain=DOMAIN,
                    version=2,
                    unique_id=spider,
                    title=name,
                    data={
                        CONF_PORT: PORT,
                        CONF_GATEWAY_ID: GATEWAY,
                        CONF_SPIDER_ID: spider,
                        CONF_NAME: name,
                    },
                    options={CONF_ENABLE_CONTROL: True},
                )
                entry.add_to_hass(hass)
                entries.append(entry)
                assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert len(buses) == 1 and buses[0].connect_count == 1
            bus = buses[0]
            down, up = [e.runtime_data.controller for e in entries]
            for spider in (SPIDER, UPSTAIRS):
                bus.on_line(packet("3110", "00000010", src=spider))
                bus.on_line(packet("01FF", STATUS_21, src=spider, dst=GATEWAY))
            await asyncio.gather(down._queue.join(), up._queue.join())
            assert down.control_ready and up.control_ready
            task = asyncio.create_task(up.async_set_temperature(21.5))
            command = await asyncio.wait_for(bus.outgoing.get(), 1)
            assert f"{GATEWAY} {UPSTAIRS}" in command and RELAY not in command
            # A downstairs report cannot confirm the upstairs command.
            bus.on_line(packet("22C9", "00086608FC01", verb="W", dst=GATEWAY))
            await down._queue.join()
            assert not task.done()
            bus.on_line(packet("22C9", "00086608FC01", verb="W", src=UPSTAIRS, dst=GATEWAY))
            await up._queue.join()
            await task
            assert up.last_command_result == "confirmed"
            assert up.state.target_temperature == 21.5
            assert any(c.startswith("I ---") and UPSTAIRS in c for c in bus.sent)
            before = list(bus.sent)
            bus.on_line(packet("3EF1", "00", verb="RQ", src=UPSTAIRS, dst=RELAY))
            bus.on_line(packet("3EF1", "000091009100FF", verb="RP", src=RELAY, dst=UPSTAIRS))
            await up._queue.join()
            assert bus.sent == before
            with pytest.raises(ValueError):
                await up.transport.async_send(f"W --- {GATEWAY} {RELAY} --:------ 0008 002 00C8")
            assert await hass.config_entries.async_unload(entries[0].entry_id)
            assert bus.close_count == 0 and up.transport.is_connected
            bus.on_line(packet("30C9", "000806", src=UPSTAIRS))
            await up._queue.join()
            assert up.state.temperature == 20.54
        finally:
            for entry in entries:
                await hass.config_entries.async_unload(entry.entry_id)
        assert buses[0].closed


async def test_shared_reconnect_and_cancelled_client_do_not_steal_connection():
    with patch("custom_components.itho_spider.shared_gateway.GatewayTransport", FakeTransport):
        gateway = SharedGateway(PORT, GATEWAY)
        seen = {SPIDER: [], UPSTAIRS: []}
        lost = []
        clients = [
            gateway.client_factory(s)(
                PORT, seen[s].append, lost.append, expected_gateway_id=GATEWAY
            )
            for s in seen
        ]
        await asyncio.gather(*(c.async_connect() for c in clients))
        bus = gateway._transport
        assert bus.connect_count == 1
        bus.disconnect()
        assert len(lost) == 2
        await asyncio.gather(*(c.async_connect() for c in clients))
        assert bus.connect_count == 2
        bus.on_line(packet("30C9", "000806", src=UPSTAIRS))
        assert len(seen[UPSTAIRS]) == 1 and not seen[SPIDER]
        await clients[0].async_close()
        assert clients[1].is_connected
        await clients[1].async_close()
        assert bus.close_count == 1


@pytest.mark.parametrize(
    "profile",
    [
        ["0022C9", "003110", "0022F1", "023EF0", "0110E0", "001FC9"],
        ["0022C9", "0022F1", "00000E", "0110E0", "001FC9"],
    ],
)
async def test_pairing_only_explicit_target_gateway_offer_and_confirmation(profile):
    with patch("custom_components.itho_spider.shared_gateway.GatewayTransport", FakeTransport):
        gateway = SharedGateway(PORT, GATEWAY)
        controller = SpiderController(
            PORT, GATEWAY, UPSTAIRS, transport_factory=gateway.client_factory(UPSTAIRS)
        )
        await controller.async_start()
        bus = gateway._transport
        own = address_hex(UPSTAIRS)
        offer = packet(
            "1FC9",
            "".join(c + own for c in profile),
            src=UPSTAIRS,
        )
        try:
            await controller.async_process_line(offer)
            assert not bus.sent
            controller.arm_pairing()
            assert not bus.sent
            await controller.async_process_line(offer.replace(UPSTAIRS, SPIDER))
            await controller.async_process_line(packet("1FC9", "003EF0" + own, src=UPSTAIRS))
            await controller.async_process_line(
                packet("1FC9", "".join(c + own for c in profile[:-1]), src=UPSTAIRS)
            )
            await controller.async_process_line(offer.replace(own, address_hex(SPIDER)))
            await controller.async_process_line(packet("1FC9", "00", src=UPSTAIRS, dst=GATEWAY))
            assert not bus.sent and controller.pairing_status == "waiting_for_offer"
            await controller.async_process_line(offer)
            assert bus.sent == [f"W --- {GATEWAY} {UPSTAIRS} --:------ 1FC9 006 0001FF49E240"]
            await controller.async_process_line(offer)  # coalesce immediate repetition
            assert len(bus.sent) == 1
            await controller.async_process_line(packet("1FC9", "00", src=UPSTAIRS, dst=GATEWAY))
            assert controller.pairing_status == "confirmed"
            assert not controller.control_ready  # still requires fresh bound status
            await controller.async_process_line(offer)
            assert len(bus.sent) == 1
            controller.arm_pairing()
            controller._pairing_until = 1
            await controller.async_process_line(offer)
            assert controller.pairing_status == "timed_out" and len(bus.sent) == 1
            controller.enable_control = False
            with pytest.raises(ControlError):
                controller.arm_pairing()
        finally:
            await controller.async_close()


async def test_migration_preserves_config_entry_and_entity_identity(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, unique_id=GATEWAY, data={CONF_SPIDER_ID: SPIDER}
    )
    entry.add_to_hass(hass)
    original_id = entry.entry_id
    assert await async_migrate_entry(hass, entry)
    assert entry.entry_id == original_id and entry.unique_id == SPIDER and entry.version == 2
