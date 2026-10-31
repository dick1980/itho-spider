"""Run the real Home Assistant platforms with simulated USB transport only."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from unittest.mock import patch

import pytest
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODES,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.itho_spider.const import (
    CONF_ENABLE_CONTROL,
    CONF_GATEWAY_ID,
    CONF_SPIDER_ID,
    CONF_WAIT_FOR_WAKEUP,
    DOMAIN,
)
from custom_components.itho_spider.controller import SpiderController
from custom_components.itho_spider.diagnostics import async_get_config_entry_diagnostics

pytestmark = pytest.mark.asyncio

GATEWAY = "18:123456"
SPIDER = "21:123456"
PORT = "/dev/serial/by-id/test-itho-spider"
NAME = "Living room test thermostat"
NO_DEVICE = "--:------"
# Recorded status layout, with 21 C target and 23 C second temperature field.
STATUS_21 = "00802A2A2ED00080000A3C28400000810480800280FF80040040"
STATUS_22 = "00802A2C2ED00080000A3C28400000810480800280FF80040040"


def packet(
    code: str,
    payload: str,
    *,
    verb: str = "I",
    src: str = SPIDER,
    dst: str = NO_DEVICE,
) -> str:
    """Build a receive line without relying on the production encoder."""
    via = src if dst == NO_DEVICE else NO_DEVICE
    return f"060 {verb} --- {src} {dst} {via} {code} {len(payload) // 2:03d} {payload}"


class FakeTransport:
    """Expose callbacks and outgoing commands without loading a serial backend."""

    def __init__(
        self,
        port: str,
        on_line: Callable[[str], None],
        on_disconnect: Callable[[Exception | None], None],
        *,
        expected_gateway_id: str,
    ) -> None:
        self.port = port
        self.expected_gateway_id = expected_gateway_id
        self.on_line = on_line
        self.on_disconnect = on_disconnect
        self.connect_count = 0
        self.close_count = 0
        self.closed = False
        self.is_connected = False
        self.sent: list[str] = []
        self.outgoing: asyncio.Queue[str] = asyncio.Queue()

    async def async_connect(self) -> str:
        self.connect_count += 1
        self.closed = False
        self.is_connected = True
        return self.expected_gateway_id

    async def async_send(self, command: str) -> None:
        if self.closed:
            raise ConnectionError("Fake USB transport is closed")
        self.sent.append(command)
        self.outgoing.put_nowait(command)

    async def async_close(self) -> None:
        self.close_count += 1
        self.closed = True
        self.is_connected = False

    def disconnect(self) -> None:
        self.closed = True
        self.is_connected = False
        self.on_disconnect(ConnectionError("Simulated USB removal"))


class IntegrationHarness:
    """Own the real entry and controller while replacing only USB transport."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.entry: MockConfigEntry | None = None
        self.controllers: list[SpiderController] = []

    def controller_factory(self, *args, **kwargs) -> SpiderController:
        kwargs["transport_factory"] = FakeTransport
        controller = SpiderController(*args, **kwargs)
        self.controllers.append(controller)
        return controller

    @property
    def controller(self) -> SpiderController:
        return self.controllers[-1]

    @property
    def transport(self) -> FakeTransport:
        assert isinstance(self.controller.transport, FakeTransport)
        return self.controller.transport

    async def setup(
        self, *, enable_control: bool = True, wait_for_wakeup: bool = False
    ) -> MockConfigEntry:
        self.entry = MockConfigEntry(
            domain=DOMAIN,
            title=NAME,
            unique_id=GATEWAY,
            data={
                CONF_PORT: PORT,
                CONF_GATEWAY_ID: GATEWAY,
                CONF_SPIDER_ID: SPIDER,
                CONF_NAME: NAME,
            },
            options={CONF_ENABLE_CONTROL: enable_control, CONF_WAIT_FOR_WAKEUP: wait_for_wakeup},
        )
        self.entry.add_to_hass(self.hass)
        assert await self.hass.config_entries.async_setup(self.entry.entry_id)
        await self.hass.async_block_till_done()
        return self.entry

    def entity_id(self, platform: str, key: str) -> str:
        entity_id = er.async_get(self.hass).async_get_entity_id(platform, DOMAIN, f"{SPIDER}_{key}")
        assert entity_id is not None, (platform, key)
        return entity_id

    def state(self, platform: str, key: str) -> State:
        state = self.hass.states.get(self.entity_id(platform, key))
        assert state is not None, (platform, key)
        return state

    async def receive(self, line: str) -> None:
        self.transport.on_line(line)
        await asyncio.wait_for(self.controller._queue.join(), timeout=1)
        # Flush callbacks without waiting for an intentionally pending HA service.
        await asyncio.sleep(0)

    async def ready(self) -> None:
        await self.receive(packet("30C9", "000843"))
        await self.receive(packet("3110", "00004010"))
        await self.receive(packet("01FF", STATUS_21, dst=GATEWAY))


@pytest.fixture
async def integration(hass: HomeAssistant) -> AsyncIterator[IntegrationHarness]:
    harness = IntegrationHarness(hass)
    with patch(
        "custom_components.itho_spider.coordinator.SpiderController",
        side_effect=harness.controller_factory,
    ):
        yield harness
        if harness.entry is not None:
            await hass.config_entries.async_unload(harness.entry.entry_id)
        # Also clean up a controller if platform setup failed before entry load.
        for controller in harness.controllers:
            await controller.async_close()
        await hass.async_block_till_done()


async def test_setup_has_no_default_target_or_radio_commands(
    integration: IntegrationHarness,
) -> None:
    entry = await integration.setup()
    controller = integration.controller
    assert controller.state.target_temperature is None
    assert controller.state.temperature is None
    assert integration.transport.connect_count == 1
    assert integration.transport.expected_gateway_id == GATEWAY
    assert integration.transport.sent == []

    climate = integration.state("climate", "climate")
    assert climate.state == STATE_UNAVAILABLE
    assert climate.attributes.get(ATTR_TEMPERATURE) is None
    assert climate.attributes.get(ATTR_CURRENT_TEMPERATURE) is None
    assert controller.control_ready is False
    assert integration.state("binary_sensor", "gateway_connected").state == STATE_ON
    assert integration.state("binary_sensor", "control_ready").state == STATE_OFF

    devices = dr.async_get(integration.hass)
    gateway = devices.async_get_device_by_identifier((DOMAIN, GATEWAY), entry.entry_id)
    spider = devices.async_get_device_by_identifier((DOMAIN, SPIDER), entry.entry_id)
    assert gateway is not None and spider is not None
    assert spider.via_device_id == gateway.id
    assert entry.runtime_data.controller is controller


async def test_received_reports_populate_real_entities(
    integration: IntegrationHarness,
) -> None:
    await integration.setup()
    await integration.ready()
    await integration.receive(packet("1060", "00C801"))

    climate = integration.state("climate", "climate")
    assert climate.state == HVACMode.HEAT
    # Climate rounds for display; the temperature sensor preserves 0.01 C.
    assert climate.attributes[ATTR_CURRENT_TEMPERATURE] == pytest.approx(21.15, abs=0.1)
    assert climate.attributes[ATTR_TEMPERATURE] == 21.0
    assert climate.attributes[ATTR_HVAC_MODES] == [HVACMode.HEAT]
    assert climate.attributes[ATTR_HVAC_ACTION] == HVACAction.HEATING
    assert climate.attributes["second_temperature_field"] == 23.0
    assert climate.attributes["control_ready"] is True
    assert integration.state("sensor", "temperature").state == "21.15"
    assert integration.state("sensor", "target_temperature").state == "21.0"
    assert integration.state("sensor", "heating_demand").state == "32.0"
    assert integration.state("sensor", "operating_mode").state == "heat"
    assert integration.state("sensor", "program_mode").state == "manual"
    assert integration.state("sensor", "battery").state == "100.0"
    assert integration.state("binary_sensor", "battery_low").state == STATE_OFF
    assert integration.state("binary_sensor", "control_ready").state == STATE_ON
    assert integration.state("sensor", "last_seen").state not in {"unknown", "unavailable"}
    assert integration.transport.sent == []

    await integration.receive(packet("30C9", "0003E8", src="21:000001"))
    await integration.receive(packet("01FF", STATUS_22, dst="18:000001"))
    assert integration.state("sensor", "temperature").state == "21.15"
    assert integration.state("sensor", "target_temperature").state == "21.0"
    assert integration.transport.sent == []


async def test_read_only_entry_rejects_climate_commands(
    integration: IntegrationHarness,
) -> None:
    await integration.setup(enable_control=False)
    await integration.ready()
    await integration.receive(packet("01FF", STATUS_21, verb="RQ", dst=GATEWAY))

    climate = integration.state("climate", "climate")
    assert climate.state == HVACMode.HEAT
    assert not climate.attributes[ATTR_SUPPORTED_FEATURES] & ClimateEntityFeature.TARGET_TEMPERATURE
    assert integration.state("binary_sensor", "control_ready").state == STATE_OFF
    with pytest.raises(HomeAssistantError):
        await integration.hass.services.async_call(
            "climate",
            "set_temperature",
            {ATTR_ENTITY_ID: climate.entity_id, ATTR_TEMPERATURE: 22.0},
            blocking=True,
        )
    assert integration.transport.sent == []
    assert integration.state("sensor", "target_temperature").state == "21.0"


async def test_battery_service_returns_pending_and_confirms_after_poll(integration):
    await integration.setup(wait_for_wakeup=True)
    await integration.ready()
    await integration.hass.services.async_call(
        "climate",
        "set_temperature",
        {ATTR_ENTITY_ID: integration.entity_id("climate", "climate"), ATTR_TEMPERATURE: 22.0},
        blocking=True,
    )
    assert integration.state("climate", "climate").attributes[ATTR_TEMPERATURE] == 21
    assert integration.state("sensor", "command_status").state == "waiting_for_thermostat"
    assert integration.state("sensor", "command_status").attributes["pending_temperature"] == 22
    await asyncio.wait_for(integration.transport.outgoing.get(), timeout=1)
    await integration.receive(packet("01FF", STATUS_21, verb="RQ", dst=GATEWAY))
    assert integration.transport.sent[-1].startswith("RP ")
    await integration.receive(packet("01FF", STATUS_22, dst=GATEWAY))
    await integration.hass.async_block_till_done()
    assert integration.state("climate", "climate").attributes[ATTR_TEMPERATURE] == 22
    assert integration.state("sensor", "command_status").state == "confirmed"
    assert integration.state("sensor", "command_status").attributes["pending_temperature"] is None


@pytest.mark.parametrize("confirmation_verb", ["I", "RQ"])
async def test_climate_service_waits_for_spider_confirmation_not_gateway_echo(
    integration: IntegrationHarness, confirmation_verb: str
) -> None:
    await integration.setup()
    await integration.ready()
    climate_id = integration.entity_id("climate", "climate")

    service = asyncio.create_task(
        integration.hass.services.async_call(
            "climate",
            "set_temperature",
            {ATTR_ENTITY_ID: climate_id, ATTR_TEMPERATURE: 22.0},
            blocking=True,
        )
    )
    try:
        command = await asyncio.wait_for(integration.transport.outgoing.get(), timeout=1)
        fields = command.split()
        assert fields[:7] == ["W", "---", GATEWAY, SPIDER, NO_DEVICE, "01FF", "026"]
        assert fields[7][6:10] == "2C2E"  # 22 C requested, 23 C second field retained.
        await integration.receive(f"000 {command}")

        assert not service.done()
        pending = integration.state("climate", "climate")
        assert pending.attributes[ATTR_TEMPERATURE] == 21.0
        assert pending.attributes["pending_temperature"] == 22.0
        assert pending.attributes["last_command_result"] == "pending"

        await integration.receive(packet("01FF", STATUS_22, verb=confirmation_verb, dst=GATEWAY))
        await asyncio.wait_for(service, timeout=1)
        await integration.hass.async_block_till_done()
        confirmed = integration.state("climate", "climate")
        assert confirmed.attributes[ATTR_TEMPERATURE] == 22.0
        assert confirmed.attributes["pending_temperature"] is None
        assert confirmed.attributes["last_command_result"] == "confirmed"
        assert integration.state("sensor", "target_temperature").state == "22.0"
        assert len(integration.transport.sent) == (2 if confirmation_verb == "RQ" else 1)
        if confirmation_verb == "RQ":
            assert integration.transport.sent[-1].startswith(f"RP --- {GATEWAY} {SPIDER} ")
    finally:
        if not service.done():
            service.cancel()
        await asyncio.gather(service, return_exceptions=True)


async def test_usb_loss_marks_reports_unavailable_and_unload_cleans_tasks(
    integration: IntegrationHarness,
) -> None:
    entry = await integration.setup()
    await integration.ready()
    entity_ids = [
        item.entity_id
        for item in er.async_entries_for_config_entry(
            er.async_get(integration.hass), entry.entry_id
        )
    ]
    integration.transport.disconnect()
    await asyncio.sleep(0)

    assert integration.state("climate", "climate").state == STATE_UNAVAILABLE
    assert integration.state("sensor", "temperature").state == STATE_UNAVAILABLE
    assert integration.state("sensor", "target_temperature").state == STATE_UNAVAILABLE
    assert integration.state("binary_sensor", "gateway_connected").state == STATE_OFF
    assert integration.state("binary_sensor", "control_ready").state == STATE_OFF
    assert integration.controller.control_ready is False

    assert await integration.hass.config_entries.async_unload(entry.entry_id)
    await integration.hass.async_block_till_done()
    assert integration.transport.closed
    assert integration.controller._worker is None
    assert integration.controller._timer is None
    assert integration.controller._reconnect is None
    # HA keeps unavailable registry placeholders after a platform is unloaded.
    for entity_id in entity_ids:
        state = integration.hass.states.get(entity_id)
        assert state is not None and state.state == STATE_UNAVAILABLE
        assert state.attributes["restored"] is True
    assert integration.transport.sent == []


async def test_diagnostics_redact_configuration_and_exclude_neighbour_traffic(
    integration: IntegrationHarness,
) -> None:
    entry = await integration.setup()
    await integration.ready()
    neighbour_packet = packet("30C9", "0003E8", src="21:000001")
    await integration.receive(neighbour_packet)

    diagnostics = await async_get_config_entry_diagnostics(integration.hass, entry)
    serialized = json.dumps(diagnostics)
    for private in (GATEWAY, SPIDER, PORT, NAME, "21:000001", neighbour_packet):
        assert private not in serialized
    assert diagnostics["entry"] == {
        CONF_PORT: "**REDACTED**",
        CONF_GATEWAY_ID: "**REDACTED**",
        CONF_SPIDER_ID: "**REDACTED**",
        CONF_NAME: "**REDACTED**",
    }
    assert diagnostics["controller"]["received_packets"] == 3
    assert diagnostics["controller"]["sent_packets"] == 0
    assert diagnostics["controller"]["control_ready"] is True


@pytest.mark.parametrize("disconnect_first", [False, True])
async def test_home_assistant_stop_closes_usb_and_cancels_background_tasks(
    integration: IntegrationHarness, disconnect_first: bool
) -> None:
    """The stop listener closes connected and reconnecting gateways before unload."""
    await integration.setup()
    await integration.ready()
    if disconnect_first:
        integration.transport.disconnect()
        await asyncio.sleep(0)

    controller = integration.controller
    tasks = [
        task
        for task in (controller._worker, controller._timer, controller._reconnect)
        if task is not None
    ]
    assert tasks and all(not task.done() for task in tasks)
    assert integration.transport.close_count == 0

    integration.hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await integration.hass.async_block_till_done()

    assert integration.transport.closed
    assert integration.transport.close_count == 1
    assert all(task.done() for task in tasks)
    assert controller._worker is None
    assert controller._timer is None
    assert controller._reconnect is None
    assert controller.connected is False
    assert controller.control_ready is False
    assert integration.transport.sent == []
