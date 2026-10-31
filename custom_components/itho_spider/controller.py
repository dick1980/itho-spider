"""Single-Spider gateway controller, independent of Home Assistant.

There is no restored/default target and no automatic pairing. A fresh manual
heating status is required for 01FF commands. A local 22C9 choice can be
acknowledged immediately by echoing its validated fields. A direct W/22C9 can
also report the result of a remote command, rather than a physical adjustment.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from .binding import gateway_accept, is_confirmation, is_gateway_offer
from .protocol import (
    ProtocolError,
    SpiderState,
    build_local_setpoint_ack,
    build_setpoint_command,
    packet_is_from_spider,
    parse_packet,
    update_state,
    validate_device_id,
)
from .transport import GatewayTransport

_LOGGER = logging.getLogger(__name__)
STALE_SECONDS = 1200.0
COMMAND_ATTEMPTS = 3
COMMAND_WAIT_SECONDS = 3.0
WAKEUP_WAIT_SECONDS = 660.0
MAX_SENDS_PER_MINUTE = 12
LOCAL_OVERRIDE_SECONDS = 120.0
REPLY_COALESCE_SECONDS = 0.25


class ControlError(Exception):
    """The requested operation cannot be performed or confirmed."""


class LocalOverrideError(ControlError):
    """The thermostat reported a different setting during a remote command."""


@dataclass
class PendingCommand:
    temperature: float
    cooling_target: float | None
    future: asyncio.Future[None]
    sends: int = 0


@dataclass
class LocalChoice:
    temperature: float
    cooling_target: float
    received_at: float


class SpiderController:
    """Own the serial connection, reported state, and bounded RF transactions."""

    def __init__(
        self,
        port: str,
        gateway_id: str,
        spider_id: str,
        *,
        enable_control: bool = True,
        wait_for_wakeup: bool = False,
        on_update: Callable[[], None] | None = None,
        transport_factory=GatewayTransport,
    ) -> None:
        self.gateway_id = validate_device_id(gateway_id, "18")
        self.spider_id = validate_device_id(spider_id, "21")
        self.enable_control = enable_control
        self.wait_for_wakeup = wait_for_wakeup
        self.on_update = on_update
        self.state = SpiderState()
        self.connected = False
        self.last_seen_utc: datetime | None = None
        self.last_error: str | None = None
        self.last_command_result: str | None = None
        self.last_confirmation: dict | None = None
        self.sent_count = 0
        self.received_count = 0
        self.dropped_count = 0
        self._bound_status_seen = False
        self._pairing_until = 0.0
        self._pairing_accepts = 0
        self._pairing_last_accept = 0.0
        self.pairing_status = "idle"
        self.pairing_event = asyncio.Event()
        self._removal_until = 0.0
        self._closing = False
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._worker: asyncio.Task | None = None
        self._reconnect: asyncio.Task | None = None
        self._timer: asyncio.Task | None = None
        self._pending: PendingCommand | None = None
        self._deferred_command: asyncio.Task | None = None
        self._local_choice: LocalChoice | None = None
        self._last_reply: tuple[str, float] | None = None
        self._command_lock = asyncio.Lock()
        self._send_times: deque[float] = deque()
        self.transport = transport_factory(
            port,
            self._on_line,
            self._on_disconnect,
            expected_gateway_id=gateway_id,
        )

    def arm_pairing(self) -> float:
        """Open a three-minute window without transmitting until a matching offer."""
        if not self.connected or not self.enable_control or self._removal_until:
            raise ControlError("Enable thermostat control and connect the gateway first")
        if self._bound_status_seen:
            raise ControlError("This Spider already reports to the gateway; no pairing needed")
        if self._pairing_until > time.monotonic():
            raise ControlError("A pairing window is already open")
        self._pairing_until = time.monotonic() + 180
        self._pairing_accepts = 0
        self._pairing_last_accept = 0.0
        self.pairing_status = "waiting_for_offer"
        self._notify()
        return self._pairing_until

    def cancel_pairing(self, token: float | None = None) -> None:
        """Cancel only the window owned by this wizard, if a token is supplied."""
        if self._pairing_until and (token is None or token == self._pairing_until):
            self._pairing_until = 0
            self.pairing_status = "cancelled"
            self._notify()

    def prepare_removal(self) -> float:
        """Pause this Spider's radio replies during a bounded physical unpair guide."""
        if self._pending is not None or self._removal_until:
            raise ControlError("A command or removal procedure is still in progress")
        self.cancel_pairing()
        self._removal_until = time.monotonic() + 600
        self._notify()
        return self._removal_until

    def finish_removal(self, token: float) -> None:
        """After cancellation, require a fresh bound report before controlling again."""
        if token == self._removal_until:
            self._removal_until = 0
            self._bound_status_seen = False
            self._notify()

    def removal_active(self, token: float) -> bool:
        return token == self._removal_until and time.monotonic() < token

    async def _process_binding(self, packet) -> None:
        if not self._pairing_until or not self.enable_control or not self.connected:
            return
        now = time.monotonic()
        if now >= self._pairing_until:
            self._pairing_until = 0
            self.pairing_status = "timed_out"
        elif self._pairing_accepts and is_confirmation(packet, self.spider_id, self.gateway_id):
            self._pairing_until = 0
            self.pairing_status = "confirmed"
        elif (
            self._pairing_accepts < 3
            and now - self._pairing_last_accept >= 1
            and is_gateway_offer(packet, self.spider_id)
        ):
            # Count before sending: an uncertain send must not become an unbounded retry.
            self._pairing_accepts += 1
            self._pairing_last_accept = now
            await self._send(gateway_accept(self.spider_id, self.gateway_id))
            self.pairing_status = "waiting_for_confirmation"
        self._notify()

    @property
    def available(self) -> bool:
        return bool(
            self.connected
            and self.state.last_seen is not None
            and time.monotonic() - self.state.last_seen < STALE_SECONDS
        )

    @property
    def control_ready(self) -> bool:
        return bool(
            self.available
            and self.enable_control
            and not self._removal_until
            and self._bound_status_seen
            and self.state.last_01ff_at is not None
            and time.monotonic() - self.state.last_01ff_at < STALE_SECONDS
            and self.state.last_setpoint_at is not None
            and time.monotonic() - self.state.last_setpoint_at < STALE_SECONDS
            and self.state.operating_mode == "heat"
            and self.state.time_planning is False
            and self.state.target_temperature is not None
            and self.state.cooling_target is not None
        )

    @property
    def pending_temperature(self) -> float | None:
        return self._pending.temperature if self._pending else None

    def _notify(self) -> None:
        self.pairing_event.set()
        if self.on_update is not None:
            self.on_update()

    async def async_start(self) -> None:
        self._closing = False
        self._worker = asyncio.create_task(self._consume(), name="itho_spider_packets")
        try:
            await self.transport.async_connect()
            if not self.transport.is_connected:
                raise ConnectionError("USB disconnected during identification")
        except BaseException:
            await self.async_close()
            raise
        self.connected = True
        self._timer = asyncio.create_task(self._tick(), name="itho_spider_freshness")
        self._notify()

    def _on_line(self, line: str) -> None:
        if self._closing:
            return
        try:
            self._queue.put_nowait(line)
        except asyncio.QueueFull:
            self.dropped_count += 1

    def _on_disconnect(self, error: Exception | None) -> None:
        self.connected = False
        self._pairing_until = 0
        if self.pairing_status in {"waiting_for_offer", "waiting_for_confirmation"}:
            self.pairing_status = "cancelled"
        self._bound_status_seen = False
        self._local_choice = None
        self._last_reply = None
        self.state = SpiderState()
        self.last_error = "USB connection lost"
        if self._pending and not self._pending.future.done():
            self._pending.future.set_exception(ControlError("USB connection lost"))
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        if not self._closing:
            _LOGGER.warning("USB connection lost; reconnecting: %s", error)
            if self._reconnect is None or self._reconnect.done():
                self._reconnect = asyncio.create_task(
                    self._reconnect_loop(), name="itho_spider_reconnect"
                )
        self._notify()

    async def _reconnect_loop(self) -> None:
        delay = 2.0
        while not self._closing:
            await asyncio.sleep(delay)
            try:
                await self.transport.async_connect()
                if not self.transport.is_connected:
                    raise ConnectionError("USB disconnected during identification")
            except OSError, TimeoutError, ValueError:
                delay = min(delay * 2, 60.0)
                continue
            self.connected = True
            self.last_error = None
            self._notify()
            return

    async def _tick(self) -> None:
        while not self._closing:
            await asyncio.sleep(30)
            if self._removal_until and time.monotonic() >= self._removal_until:
                self.finish_removal(self._removal_until)
            if self._pairing_until and time.monotonic() >= self._pairing_until:
                self._pairing_until = 0
                self.pairing_status = "timed_out"
            self._notify()

    async def _consume(self) -> None:
        while not self._closing:
            line = await self._queue.get()
            try:
                await self.async_process_line(line)
            except (OSError, TimeoutError, ProtocolError, ControlError) as exc:
                self.last_error = str(exc)
                _LOGGER.debug("Spider message handling stopped: %s", exc)
                self._notify()
            except Exception:
                _LOGGER.exception("Unexpected error processing Spider message")
            finally:
                self._queue.task_done()

    async def async_process_line(self, line: str) -> None:
        """Process a received packet; also usable with recorded traffic in tests."""
        packet = parse_packet(line)
        if packet is None or not packet_is_from_spider(packet, self.spider_id, self.gateway_id):
            return
        if packet.code == "1FC9":
            await self._process_binding(packet)
            return
        previous = self.state
        updated = update_state(previous, packet, self.spider_id, self.gateway_id)
        if updated is previous:
            return
        now = time.monotonic()
        local_write = packet.code == "22C9" and packet.verb == "W" and packet.dst == self.gateway_id
        local_ack = None
        if local_write:
            try:
                local_ack = build_local_setpoint_ack(packet, self.spider_id, self.gateway_id)
            except ProtocolError:
                self._local_choice = None
        if local_ack is not None:
            self._local_choice = LocalChoice(
                updated.target_temperature, updated.cooling_target, now
            )
        elif packet.code == "01FF" and self._local_choice is not None:
            local = self._local_choice
            if (
                packet.dst == self.gateway_id
                and packet.verb in {"I", "RQ"}
                and updated.target_temperature == local.temperature
                and updated.cooling_target == local.cooling_target
            ) or now - local.received_at >= LOCAL_OVERRIDE_SECONDS:
                self._local_choice = None
            else:
                # An earlier gateway value can still appear in the first RQ
                # after a 22C9 setpoint report. Do not reply with that old value.
                updated = replace(
                    updated,
                    target_temperature=local.temperature,
                    cooling_target=local.cooling_target,
                    last_setpoint_at=local.received_at,
                )
        self.state = updated
        self.received_count += 1
        self.last_seen_utc = datetime.now(UTC)
        if packet.code == "01FF" and packet.dst == self.gateway_id:
            self._bound_status_seen = True

        pending = self._pending
        if pending and not pending.future.done():
            if self.wait_for_wakeup and (
                updated.operating_mode != "heat" or updated.time_planning is not False
            ):
                pending.future.set_exception(ControlError("Thermostat left manual heating mode"))
                self._pending = None
                self.last_command_result = "cancelled_mode_change"
                self._notify()
                return
            target_matches = (
                updated.target_temperature == pending.temperature
                and updated.cooling_target is not None
                and updated.operating_mode == "heat"
                and updated.time_planning is False
            )
            confirms_command = False
            if local_write:
                unchanged_report = (
                    self.wait_for_wakeup
                    and local_ack is not None
                    and updated.target_temperature == previous.target_temperature
                    and updated.cooling_target == previous.cooling_target
                )
                if local_ack is not None and target_matches:
                    # Live Spider responses use W/22C9 after W/01FF as well as
                    # after physical changes. A matching target is a readback,
                    # not an override. The device may change its second field.
                    confirms_command = True
                elif not unchanged_report:
                    # Battery Spiders repeat their unchanged setting in W/22C9
                    # immediately before RQ/01FF. That is not a local change.
                    pending.future.set_exception(
                        LocalOverrideError(
                            "The thermostat reported a different setting; its setting takes priority"
                        )
                    )
                    self._pending = None
                    self.last_command_result = "overridden_locally"
            elif (
                packet.code == "01FF"
                and packet.dst == self.gateway_id
                and packet.verb in {"I", "RQ"}
                and target_matches
            ):
                # The primary Spider logs also show the second field changing
                # between a W/01FF command and its I/01FF response. Preserve the
                # returned field; do not demand an echo or synthesize a delta.
                confirms_command = True
            if confirms_command:
                pending.future.set_result(None)
                self.last_command_result = "confirmed"
                self.last_confirmation = {
                    "message": f"{packet.verb}/{packet.code}",
                    "target_temperature": updated.target_temperature,
                    "second_temperature_field": updated.cooling_target,
                    "received_at": self.last_seen_utc.isoformat(),
                }

        self._notify()
        if (
            local_ack is not None
            and self.connected
            and self.enable_control
            and not self._removal_until
        ):
            await self._send_reply(local_ack)
            return
        if not self.control_ready or packet.dst != self.gateway_id:
            return
        if packet.code == "01FF" and packet.verb == "RQ":
            # During a bounded user command, do not undo it with an old report.
            pending = self._pending
            target = (
                pending.temperature
                if pending is not None and not pending.future.done()
                else self.state.target_temperature
            )
            command = build_setpoint_command(
                self.spider_id, self.gateway_id, target, self.state, verb="RP"
            )
            if self.wait_for_wakeup and pending is not None and not pending.future.done():
                if pending.sends >= COMMAND_ATTEMPTS:
                    return
                pending.sends += 1
            await self._send_reply(command)

    async def _send_reply(self, command: str) -> None:
        now = time.monotonic()
        if self._last_reply is not None:
            previous, timestamp = self._last_reply
            if command == previous and now - timestamp < REPLY_COALESCE_SECONDS:
                return
        await self._send(command)
        self._last_reply = (command, now)

    async def _send(self, command: str) -> None:
        if self._closing or not self.connected or not self.enable_control or self._removal_until:
            raise ControlError("Gateway control is unavailable")
        now = time.monotonic()
        while self._send_times and now - self._send_times[0] >= 60:
            self._send_times.popleft()
        if len(self._send_times) >= MAX_SENDS_PER_MINUTE:
            raise ControlError("Radio command rate limit reached; try again later")
        self._send_times.append(now)
        await self.transport.async_send(command.rstrip("\r\n"))
        self.sent_count += 1

    async def async_set_temperature(self, temperature: float) -> None:
        """Wait for a Spider report, never mistake a gateway echo for success."""
        if self._command_lock.locked():
            raise ControlError("Another temperature command is awaiting confirmation")
        async with self._command_lock:
            if not self.control_ready:
                raise ControlError(
                    "Waiting for a fresh status from the paired Spider in manual heating mode"
                )
            command = build_setpoint_command(
                self.spider_id, self.gateway_id, temperature, self.state
            )
            if self._deferred_command is not None:
                self._deferred_command.cancel()
                with suppress(asyncio.CancelledError):
                    await self._deferred_command
                self._deferred_command = None
            future = asyncio.get_running_loop().create_future()
            pending = PendingCommand(temperature, self.state.cooling_target, future)
            self._local_choice = None
            self._pending = pending
            if self.wait_for_wakeup:
                self.last_command_result = "waiting_for_thermostat"
                self.last_error = None
                self.last_confirmation = None
                self._notify()
                self._deferred_command = asyncio.create_task(
                    self._await_wakeup(pending, command), name="itho_spider_wait_for_wakeup"
                )
                return
            self.last_command_result = "pending"
            self.last_confirmation = None
            self._notify()
            try:
                for _ in range(COMMAND_ATTEMPTS):
                    if future.done():
                        await future
                        return
                    if not self.control_ready:
                        raise ControlError("Spider is no longer ready for control")
                    await self._send(command)
                    try:
                        await asyncio.wait_for(asyncio.shield(future), COMMAND_WAIT_SECONDS)
                    except TimeoutError:
                        continue
                    self.last_error = None
                    self.last_command_result = "confirmed"
                    return
                self.last_command_result = "unconfirmed"
                raise ControlError(
                    "The Spider did not confirm the temperature; check its display before retrying"
                )
            except asyncio.CancelledError:
                self.last_command_result = "cancelled_unconfirmed"
                raise
            except (OSError, TimeoutError, ProtocolError, ControlError) as exc:
                self.last_error = str(exc)
                if self.last_command_result == "pending":
                    self.last_command_result = "failed"
                raise
            finally:
                if not future.done():
                    future.cancel()
                elif not future.cancelled():
                    # Retrieve an exception that raced with a failed serial send.
                    future.exception()
                if self._pending is pending:
                    self._pending = None
                self._notify()

    async def _await_wakeup(self, pending: PendingCommand, command: str) -> None:
        """Try once immediately, then answer a poll within one bounded wakeup cycle."""
        future = pending.future
        try:
            pending.sends += 1
            await self._send(command)
            await asyncio.wait_for(asyncio.shield(future), WAKEUP_WAIT_SECONDS)
            self.last_error = None
            self.last_command_result = "confirmed"
        except TimeoutError:
            self.last_error = "The Spider did not confirm the queued temperature within 11 minutes"
            self.last_command_result = "unconfirmed"
        except asyncio.CancelledError:
            self.last_command_result = "cancelled_unconfirmed"
            raise
        except (OSError, ProtocolError, ControlError) as exc:
            self.last_error = str(exc)
            if self.last_command_result == "waiting_for_thermostat":
                self.last_command_result = "failed"
        finally:
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()
            if self._pending is pending:
                self._pending = None
            if self._deferred_command is asyncio.current_task():
                self._deferred_command = None
            self._notify()

    async def async_close(self) -> None:
        self._closing = True
        self.connected = False
        self._pairing_until = 0
        if self.pairing_status in {"waiting_for_offer", "waiting_for_confirmation"}:
            self.pairing_status = "cancelled"
        self._bound_status_seen = False
        if self._pending and not self._pending.future.done():
            self._pending.future.set_exception(ControlError("Integration stopped"))
        tasks = [
            t
            for t in (self._worker, self._reconnect, self._timer, self._deferred_command)
            if t is not None
        ]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        await self.transport.async_close()
        self._worker = self._reconnect = self._timer = None
        self._deferred_command = None

    def diagnostics(self) -> dict:
        """Operational diagnostics; no raw RF traffic from neighbours."""
        return {
            "pairing_status": self.pairing_status,
            "pairing_accepts": self._pairing_accepts,
            "connected": self.connected,
            "available": self.available,
            "control_enabled": self.enable_control,
            "wait_for_wakeup": self.wait_for_wakeup,
            "removal_in_progress": bool(self._removal_until),
            "control_ready": self.control_ready,
            "bound_status_seen": self._bound_status_seen,
            "last_error": self.last_error,
            "last_command_result": self.last_command_result,
            "last_confirmation": self.last_confirmation,
            "pending_temperature": self.pending_temperature,
            "received_packets": self.received_count,
            "sent_packets": self.sent_count,
            "dropped_packets": self.dropped_count,
            "raw_01ff": self.state.raw_01ff.hex().upper() if self.state.raw_01ff else None,
        }
