"""Real asyncio controller transactions against an in-memory USB transport.

No Home Assistant runtime or physical serial device is used by these tests.
The isolated package import avoids the integration's Home Assistant __init__.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

PACKAGE_NAME = "_itho_spider_controller_tests"
package = ModuleType(PACKAGE_NAME)
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "itho_spider")]
sys.modules.setdefault(PACKAGE_NAME, package)
controller_module = importlib.import_module(f"{PACKAGE_NAME}.controller")
protocol = importlib.import_module(f"{PACKAGE_NAME}.protocol")

SpiderController = controller_module.SpiderController
ControlError = controller_module.ControlError
LocalOverrideError = controller_module.LocalOverrideError
SPIDER = "21:123456"
GATEWAY = "18:123456"
OTHER_GATEWAY = "18:000001"
STATUS = "00802C2428D00080000A3C28400000810480800280FF80040040"


def receive(
    code: str,
    payload: str,
    *,
    verb: str = "I",
    src: str = SPIDER,
    dst: str = GATEWAY,
    rssi: str = "062",
) -> str:
    return f"{rssi} {verb} --- {src} {dst} --:------ {code} {len(payload) // 2:03d} {payload}"


def status(target: float = 18, cooling: float = 20, *, verb: str = "I", dst: str = GATEWAY):
    payload = bytearray.fromhex(STATUS)
    payload[3] = round(target * 2)
    payload[4] = round(cooling * 2)
    return receive("01FF", payload.hex(), verb=verb, dst=dst)


def sent_packet(command: str):
    packet = protocol.parse_packet("000 " + command)
    assert packet is not None
    return packet


class FakeTransport:
    """Retains actual serialized commands and never accesses /dev."""

    def __init__(self, port, on_line, on_disconnect, *, expected_gateway_id):
        self.port = port
        self.on_line = on_line
        self.on_disconnect = on_disconnect
        self.gateway_id = expected_gateway_id
        self.is_connected = False
        self.connect_count = 0
        self.close_count = 0
        self.sent: list[str] = []
        self.failure: Exception | None = None

    async def async_connect(self):
        self.connect_count += 1
        self.is_connected = True
        return self.gateway_id

    async def async_send(self, command):
        if self.failure:
            raise self.failure
        self.sent.append(command)

    async def async_close(self):
        self.close_count += 1
        self.is_connected = False


async def spin_until(predicate):
    async with asyncio.timeout(1):
        while not predicate():  # noqa: ASYNC110 - bounded scheduler helper
            await asyncio.sleep(0)


@pytest.fixture
async def controller():
    result = SpiderController(
        "/dev/software-test-only", GATEWAY, SPIDER, transport_factory=FakeTransport
    )
    await result.async_start()
    try:
        yield result
    finally:
        await result.async_close()


async def make_ready(controller):
    await controller.async_process_line(receive("3110", "00000010"))
    await controller.async_process_line(status())
    assert controller.control_ready
    assert controller.transport.sent == []


async def test_battery_command_waits_for_poll_without_optimistic_state(controller):
    await make_ready(controller)
    controller.wait_for_wakeup = True
    await controller.async_set_temperature(19.5)
    assert controller.pending_temperature == 19.5
    assert controller.state.target_temperature == 18
    assert controller.last_command_result == "waiting_for_thermostat"
    await spin_until(lambda: len(controller.transport.sent) == 1)
    assert sent_packet(controller.transport.sent[0]).verb == "W"
    await controller.async_process_line(status(verb="RQ"))
    reply = sent_packet(controller.transport.sent[-1])
    assert reply.verb == "RP" and reply.payload[3] == 39
    assert controller.pending_temperature == 19.5
    await controller.async_process_line(status(19.5))
    await spin_until(lambda: controller._deferred_command is None)
    assert controller.last_command_result == "confirmed"
    assert controller.pending_temperature is None
    assert controller.state.target_temperature == 19.5


async def test_battery_command_timeout_never_replays_later(controller, monkeypatch):
    await make_ready(controller)
    controller.wait_for_wakeup = True
    monkeypatch.setattr(controller_module, "WAKEUP_WAIT_SECONDS", 0.01)
    await controller.async_set_temperature(19.5)
    await spin_until(lambda: controller._deferred_command is None)
    assert controller.last_command_result == "unconfirmed"
    assert controller.pending_temperature is None
    await controller.async_process_line(status(verb="RQ"))
    assert sent_packet(controller.transport.sent[-1]).payload[3] == 36


async def test_battery_periodic_unchanged_22c9_preserves_queued_command(controller):
    """Replay the upstairs wakeup sequence observed on 2026-10-31."""
    await make_ready(controller)
    await controller.async_process_line(status(19, 21))
    controller.wait_for_wakeup = True
    await controller.async_set_temperature(19.5)
    await spin_until(lambda: len(controller.transport.sent) == 1)
    await controller.async_process_line(receive("22C9", "00076C083401", verb="W"))
    assert sent_packet(controller.transport.sent[-1]).code == "22C9"
    assert controller.pending_temperature == 19.5
    assert controller.last_command_result == "waiting_for_thermostat"
    await controller.async_process_line(status(19, 21, verb="RQ"))
    reply = sent_packet(controller.transport.sent[-1])
    assert reply.verb == "RP" and reply.payload[3] == 39
    await controller.async_process_line(status(19.5, 21.5))
    await spin_until(lambda: controller._deferred_command is None)
    assert controller.last_command_result == "confirmed"
    assert controller.state.target_temperature == 19.5


async def test_battery_command_local_override_cancels_wait(controller):
    await make_ready(controller)
    controller.wait_for_wakeup = True
    await controller.async_set_temperature(19.5)
    await spin_until(lambda: len(controller.transport.sent) == 1)
    await controller.async_process_line(receive("22C9", "0007D0089801", verb="W"))
    await spin_until(lambda: controller._deferred_command is None)
    assert controller.last_command_result == "overridden_locally"
    assert controller.state.target_temperature == 20
    assert controller.pending_temperature is None


async def test_battery_command_new_selection_supersedes_old(controller):
    await make_ready(controller)
    controller.wait_for_wakeup = True
    await controller.async_set_temperature(19.5)
    await spin_until(lambda: len(controller.transport.sent) == 1)
    await controller.async_set_temperature(20.5)
    await spin_until(lambda: len(controller.transport.sent) == 2)
    await controller.async_process_line(status(verb="RQ"))
    assert sent_packet(controller.transport.sent[-1]).payload[3] == 41
    assert controller.pending_temperature == 20.5
    await controller.async_process_line(status(20.5))
    await spin_until(lambda: controller._deferred_command is None)
    assert controller.last_command_result == "confirmed"


@pytest.mark.parametrize("stop", ["disconnect", "close", "mode"])
async def test_battery_command_is_not_replayed_after_stop(controller, stop):
    await make_ready(controller)
    controller.wait_for_wakeup = True
    await controller.async_set_temperature(19.5)
    await spin_until(lambda: len(controller.transport.sent) == 1)
    if stop == "disconnect":
        controller._on_disconnect(ConnectionError("test"))
    elif stop == "close":
        await controller.async_close()
    else:
        await controller.async_process_line(receive("3110", "00000020"))
    await spin_until(lambda: controller._deferred_command is None)
    assert controller.pending_temperature is None
    assert len(controller.transport.sent) == 1


async def test_battery_command_send_budget_bounds_repeated_polls(controller):
    await make_ready(controller)
    controller.wait_for_wakeup = True
    await controller.async_set_temperature(19.5)
    await spin_until(lambda: len(controller.transport.sent) == 1)
    for _ in range(6):
        controller._last_reply = None
        await controller.async_process_line(status(verb="RQ"))
    assert len(controller.transport.sent) == 3


async def test_startup_has_no_default_target_or_rf_transmission(controller):
    assert controller.transport.connect_count == 1
    assert controller.state.target_temperature is None
    assert controller.state.raw_01ff is None
    assert not controller.available
    assert not controller.control_ready
    with pytest.raises(ControlError):
        await controller.async_set_temperature(21)
    assert controller.transport.sent == []


async def test_fresh_direct_manual_heat_status_is_required(controller):
    await controller.async_process_line(receive("30C9", "000843"))
    await controller.async_process_line(receive("3110", "00000010"))
    await controller.async_process_line(status(dst=SPIDER))
    assert controller.available
    assert not controller.control_ready
    assert controller.transport.sent == []
    await controller.async_process_line(status())
    assert controller.control_ready
    controller.state = replace(
        controller.state,
        last_01ff_at=controller.state.last_01ff_at - controller_module.STALE_SECONDS - 1,
    )
    assert not controller.control_ready
    with pytest.raises(ControlError):
        await controller.async_set_temperature(21)
    assert controller.transport.sent == []


async def test_other_gateway_and_other_spider_cannot_change_state_or_trigger_reply(controller):
    await make_ready(controller)
    initial = controller.state
    await controller.async_process_line(status(25, verb="RQ", dst=OTHER_GATEWAY))
    await controller.async_process_line(
        receive("22C9", "0009C407D001", verb="W", dst=OTHER_GATEWAY)
    )
    await controller.async_process_line(receive("01FF", STATUS, verb="RQ", src="21:000001"))
    assert controller.state is initial
    assert controller.transport.sent == []


async def test_read_only_mode_learns_reports_but_never_sends(controller):
    controller.enable_control = False
    await controller.async_process_line(receive("3110", "00000010"))
    await controller.async_process_line(status(verb="RQ"))
    await controller.async_process_line(receive("22C9", "00083407D001", verb="W"))
    assert controller.state.target_temperature == 21
    assert controller.available
    assert not controller.control_ready
    with pytest.raises(ControlError):
        await controller.async_set_temperature(22)
    assert controller.transport.sent == []


async def test_rq_reply_preserves_observed_second_field_and_manual_profile(controller):
    await make_ready(controller)
    await controller.async_process_line(status(21, 20, verb="RQ"))
    (reply,) = map(sent_packet, controller.transport.sent)
    assert (reply.verb, reply.src, reply.dst, reply.code) == ("RP", GATEWAY, SPIDER, "01FF")
    assert reply.payload[3:6] == bytes.fromhex("2A28D0")
    assert controller.state.target_temperature == 21


async def test_transmit_echo_is_not_confirmation_or_reported_target(controller):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21))
    try:
        await spin_until(lambda: bool(controller.transport.sent))
        assert controller.state.target_temperature == 18
        assert controller.pending_temperature == 21
        await controller.async_process_line("000 " + controller.transport.sent[0])
        assert controller.state.target_temperature == 18
        assert not operation.done()
        assert not controller._pending.future.done()
        await controller.async_process_line(status(21))
        await operation
        assert controller.state.target_temperature == 21
        assert controller.last_command_result == "confirmed"
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.parametrize("verb", ["I", "RQ"])
async def test_direct_01ff_matching_target_accepts_device_returned_second_field(controller, verb):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21))
    try:
        await spin_until(lambda: bool(controller.transport.sent))
        await controller.async_process_line(status(21, 23, verb=verb))
        await operation
        assert controller.state.target_temperature == 21
        assert controller.state.cooling_target == 23
        assert controller.last_command_result == "confirmed"
        assert controller.last_confirmation["message"] == f"{verb}/01FF"
        assert controller.last_confirmation["second_temperature_field"] == 23
        if verb == "RQ":
            assert sent_packet(controller.transport.sent[-1]).payload[3:5] == bytes.fromhex("2A2E")
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.parametrize(
    ("initial_target", "initial_second", "requested", "reported_second", "payload"),
    [
        (21, 23, 21.5, 23.5, "000866092E01"),
        (21.5, 23.5, 21, 23, "00083408FC01"),
        (21, 23, 21.5, 20, "00086607D001"),
    ],
)
async def test_matching_w22c9_confirms_and_acknowledges_device_fields(
    controller, initial_target, initial_second, requested, reported_second, payload
):
    """Replay both live steps, plus a valid report without a fixed +2 C delta."""
    await make_ready(controller)
    await controller.async_process_line(status(initial_target, initial_second))
    before_raw = controller.state.raw_01ff
    operation = asyncio.create_task(controller.async_set_temperature(requested))
    try:
        await spin_until(lambda: bool(controller.transport.sent))
        # The command still retains the previously observed second field.
        original = sent_packet(controller.transport.sent[0])
        assert original.code == "01FF"
        assert original.payload[4] == round(initial_second * 2)
        await controller.async_process_line(receive("22C9", payload, verb="W"))
        await operation
        assert controller.last_command_result == "confirmed"
        assert controller.pending_temperature is None
        assert controller.state.target_temperature == requested
        assert controller.state.cooling_target == reported_second
        # Do not forge a newer 01FF report from the 22C9 response.
        assert controller.state.raw_01ff == before_raw
        confirmation = controller.diagnostics()["last_confirmation"]
        assert confirmation["message"] == "W/22C9"
        assert confirmation["target_temperature"] == requested
        assert confirmation["second_temperature_field"] == reported_second
        assert confirmation["received_at"]
        assert len(controller.transport.sent) == 2
        reply = sent_packet(controller.transport.sent[-1])
        assert (reply.verb, reply.code, reply.payload_hex) == ("I", "22C9", payload)
        # A delayed status request must not undo either device-returned field.
        await controller.async_process_line(status(initial_target, initial_second, verb="RQ"))
        reply = sent_packet(controller.transport.sent[-1])
        assert reply.verb == "RP"
        assert reply.payload[3] == round(requested * 2)
        assert reply.payload[4] == round(reported_second * 2)
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.parametrize(
    "line",
    [
        receive("22C9", "000866092E01", verb="W", src="21:000001"),
        receive("22C9", "000866092E01", verb="W", dst=OTHER_GATEWAY),
        receive("22C9", "000866092E01", verb="W", src=GATEWAY, dst=SPIDER, rssi="000"),
        receive("22C9", "000866092E01", verb="W", dst=protocol.NO_DEVICE),
        receive("22C9", "000866092E01", verb="I"),
    ],
)
async def test_w22c9_confirmation_requires_exact_source_destination_and_verb(controller, line):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21.5))
    try:
        await spin_until(lambda: bool(controller.transport.sent))
        await controller.async_process_line(line)
        assert not controller._pending.future.done()
        assert controller.last_confirmation is None
        assert len(controller.transport.sent) == 1
        await controller.async_process_line(receive("22C9", "000866092E01", verb="W"))
        await operation
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.parametrize(
    "payload", ["000866092E02", "000866092E00", "0008667FFF01", "000866092D01"]
)
async def test_nonheat_or_invalid_w22c9_cannot_confirm_or_receive_ack(controller, payload):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21.5))
    try:
        await spin_until(lambda: bool(controller.transport.sent))
        await controller.async_process_line(receive("22C9", payload, verb="W"))
        with pytest.raises(LocalOverrideError):
            await operation
        assert controller.last_confirmation is None
        assert controller.last_command_result == "overridden_locally"
        assert len(controller.transport.sent) == 1
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.parametrize("invalid_state", ["cool", "off", "schedule", "missing_second"])
async def test_01ff_confirmation_requires_valid_second_field_and_manual_heating(
    controller, invalid_state
):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21))
    try:
        await spin_until(lambda: bool(controller.transport.sent))
        payload = bytearray.fromhex(STATUS)
        payload[3:5] = bytes.fromhex("2A2E")
        if invalid_state in {"cool", "off"}:
            mode = "20" if invalid_state == "cool" else "00"
            await controller.async_process_line(receive("3110", f"000000{mode}"))
        elif invalid_state == "schedule":
            payload[5] = 0x90
        else:
            payload[4] = 0x7F
        await controller.async_process_line(receive("01FF", payload.hex()))
        assert not controller._pending.future.done()
        assert controller.last_confirmation is None
        assert len(controller.transport.sent) == 1
        await controller.async_process_line(receive("3110", "00000010"))
        await controller.async_process_line(status(21, 23))
        await operation
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


async def test_only_direct_i_or_rq_status_confirms_remote_command(controller):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21))
    try:
        await spin_until(lambda: bool(controller.transport.sent))
        await controller.async_process_line(status(21, verb="RP"))
        assert not operation.done()
        assert not controller._pending.future.done()
        await controller.async_process_line(status(21, dst=SPIDER))
        assert not operation.done()
        assert not controller._pending.future.done()
        await controller.async_process_line(status(21, verb="RQ"))
        await operation
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


async def test_concurrent_remote_command_is_rejected_instead_of_queued(controller):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21))
    try:
        await spin_until(lambda: bool(controller.transport.sent))
        async with asyncio.timeout(1):
            with pytest.raises(ControlError):
                await controller.async_set_temperature(24)
        assert len(controller.transport.sent) == 1
        await controller.async_process_line(receive("22C9", "00080207D001", verb="W"))
        with pytest.raises(LocalOverrideError):
            await operation
        assert not any(
            packet.code == "01FF" and packet.payload[3] == 48
            for packet in map(sent_packet, controller.transport.sent)
        )
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


async def test_pending_target_is_used_in_rp_without_faking_confirmation(controller):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21))
    try:
        await spin_until(lambda: bool(controller.transport.sent))
        await controller.async_process_line(status(18, 20, verb="RQ"))
        reply = sent_packet(controller.transport.sent[-1])
        assert reply.verb == "RP"
        assert reply.payload[3:5] == bytes.fromhex("2A28")
        assert controller.state.target_temperature == 18
        assert not operation.done()
        assert not controller._pending.future.done()
        await controller.async_process_line(status(21, 20, verb="RQ"))
        await operation
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


async def test_local_adjustment_cancels_pending_command_and_echoes_exact_fields(controller):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(23))
    await spin_until(lambda: bool(controller.transport.sent))
    await controller.async_process_line(receive("22C9", "00083407D001", verb="W"))
    with pytest.raises(LocalOverrideError):
        await operation
    assert controller.state.target_temperature == 21
    assert controller.pending_temperature is None
    assert controller.last_command_result == "overridden_locally"
    reply = sent_packet(controller.transport.sent[-1])
    assert (reply.verb, reply.code, reply.payload_hex) == ("I", "22C9", "00083407D001")


@pytest.mark.parametrize("before_initial_status", [True, False])
async def test_local_choice_is_not_undone_by_old_01ff_request(controller, before_initial_status):
    await controller.async_process_line(receive("3110", "00000010"))
    if not before_initial_status:
        await controller.async_process_line(status())
    await controller.async_process_line(receive("22C9", "00083407D001", verb="W"))
    await controller.async_process_line(status(18, 20, verb="RQ"))
    replies = [sent_packet(command) for command in controller.transport.sent]
    status_replies = [packet for packet in replies if packet.code == "01FF"]
    assert status_replies, "A fresh direct RQ in manual heat mode should receive a reply"
    assert all(packet.payload[3] == 42 for packet in status_replies), (
        "An old RQ report must not make the gateway undo the user's local 21 C choice"
    )


async def test_local_write_is_acknowledged_before_any_01ff_report(controller):
    await controller.async_process_line(receive("22C9", "00083407D001", verb="W"))
    assert controller.state.raw_01ff is None
    assert not controller.control_ready
    (reply,) = map(sent_packet, controller.transport.sent)
    assert (reply.verb, reply.code, reply.payload_hex) == ("I", "22C9", "00083407D001")


async def test_expired_local_choice_is_not_forced_into_future_replies(controller):
    await make_ready(controller)
    await controller.async_process_line(receive("22C9", "00083407D001", verb="W"))
    controller._local_choice.received_at -= controller_module.LOCAL_OVERRIDE_SECONDS + 1
    await controller.async_process_line(status(18, 20, verb="RQ"))
    reply = sent_packet(controller.transport.sent[-1])
    assert reply.verb == "RP"
    assert reply.payload[3:5] == bytes.fromhex("2428")
    assert controller._local_choice is None


async def test_matching_status_releases_local_choice(controller):
    await make_ready(controller)
    await controller.async_process_line(receive("22C9", "00083407D001", verb="W"))
    await controller.async_process_line(status(21, 20))
    assert controller._local_choice is None
    await controller.async_process_line(status(22, 20, verb="RQ"))
    assert sent_packet(controller.transport.sent[-1]).payload[3:5] == bytes.fromhex("2C28")


async def test_identical_request_retransmissions_are_coalesced(controller):
    await make_ready(controller)
    for _ in range(3):
        await controller.async_process_line(status(verb="RQ"))
    assert len(controller.transport.sent) == 1
    assert sent_packet(controller.transport.sent[0]).verb == "RP"


async def test_rf_retry_after_coalescing_window_still_receives_reply(controller):
    await make_ready(controller)
    await controller.async_process_line(status(verb="RQ"))
    command, timestamp = controller._last_reply
    controller._last_reply = (command, timestamp - 0.43)
    await controller.async_process_line(status(verb="RQ"))
    assert len(controller.transport.sent) == 2


async def test_unknown_local_write_gets_no_response(controller):
    await make_ready(controller)
    await controller.async_process_line(receive("22D0", "00083407D001", verb="W"))
    assert controller.transport.sent == []


async def test_nonzero_local_context_never_changes_target_or_gets_ack(controller):
    await make_ready(controller)
    previous = controller.state
    await controller.async_process_line(receive("22C9", "01083407D001", verb="W"))
    assert controller.state is previous
    assert controller.transport.sent == []


@pytest.mark.parametrize("payload", ["00083407D002", "00084307D001"])
async def test_unsupported_local_write_does_not_create_a_forced_heat_choice(controller, payload):
    await make_ready(controller)
    # The report may update observed state, but must not seed a later heating
    # response when the strict local-ack profile rejected its mode or steps.
    try:
        await controller.async_process_line(receive("22C9", payload, verb="W"))
    except protocol.ProtocolError:
        pass
    assert controller._local_choice is None
    assert controller.transport.sent == []


async def test_disconnect_invalidates_write_readiness_and_cancels_pending(controller):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21))
    await spin_until(lambda: bool(controller.transport.sent))
    controller.transport.on_disconnect(OSError("software unplug"))
    with pytest.raises(ControlError, match="USB"):
        await operation
    assert not controller.available
    assert not controller.control_ready
    assert controller.state.raw_01ff is None
    assert controller.state.last_01ff_at is None
    with pytest.raises(ControlError):
        await controller.async_set_temperature(21)
    assert len(controller.transport.sent) == 1


async def test_missing_confirmation_is_bounded_and_does_not_change_reported_target(
    controller, monkeypatch
):
    await make_ready(controller)
    monkeypatch.setattr(controller_module, "COMMAND_WAIT_SECONDS", 0.001)
    with pytest.raises(ControlError, match="confirm"):
        await controller.async_set_temperature(21)
    assert len(controller.transport.sent) == controller_module.COMMAND_ATTEMPTS
    assert controller.state.target_temperature == 18
    assert controller.pending_temperature is None
    assert controller.last_command_result == "unconfirmed"


async def test_failed_send_is_not_retried_as_if_delivery_were_known(controller):
    await make_ready(controller)
    controller.transport.failure = OSError("software serial failure")
    with pytest.raises(OSError):
        await controller.async_set_temperature(21)
    assert controller.pending_temperature is None
    assert controller.state.target_temperature == 18
    assert controller.last_command_result == "failed"


async def test_cancelled_service_call_does_not_leave_permanent_pending_diagnostics(controller):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21))
    await spin_until(lambda: bool(controller.transport.sent))
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert controller.pending_temperature is None
    assert controller.state.target_temperature == 18
    assert controller.last_command_result not in {"pending", "confirmed"}


async def test_shutdown_cancels_pending_and_releases_transport(controller):
    await make_ready(controller)
    operation = asyncio.create_task(controller.async_set_temperature(21))
    await spin_until(lambda: bool(controller.transport.sent))
    await controller.async_close()
    with pytest.raises(ControlError):
        await operation
    assert not controller.available
    assert not controller.control_ready
    assert controller.transport.close_count >= 1
    assert controller._worker is controller._timer is controller._reconnect is None
