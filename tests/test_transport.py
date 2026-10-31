"""USB lifecycle tests using real asyncio streams, never physical hardware."""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.itho_spider import transport


def gateway_transport(*args, **kwargs):
    kwargs.setdefault("expected_gateway_id", "18:123456")
    return transport.GatewayTransport(*args, **kwargs)


class FakeWriter:
    """Minimal serial StreamWriter with observable ownership and backpressure."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False
        self.transport = Mock()
        self.wait_closed = AsyncMock()
        self.drain = AsyncMock()

    def write(self, data: bytes) -> None:
        if self.closed:
            raise ConnectionError("closed")
        self.writes.append(data)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def serial_pair(monkeypatch):
    """Patch only the backend opener; exercise the actual reader and tasks."""
    reader = asyncio.StreamReader()
    writer = FakeWriter()
    opener = AsyncMock(return_value=(reader, writer))
    monkeypatch.setattr(transport, "open_serial_connection", opener)
    return reader, writer, opener


async def spin_until(predicate) -> None:
    """Give tasks a bounded opportunity to run without timing-based sleeps."""
    async with asyncio.timeout(1):
        while not predicate():  # noqa: ASYNC110 - bounded test-only scheduler helper
            await asyncio.sleep(0)


@pytest.mark.parametrize(
    "port",
    [
        "socket://127.0.0.1:1234",
        "rfc2217://example:23",
        "esphome://example",
        "relative-device",
        "/tmp/capture.txt",
        "/dev/../tmp/file",
        "/dev/serial/",
        "/dev/ttyUSB0\n!B",
        "/dev/ttyUSB0\x00",
        "/dev/ttyUSB0?port=1",
    ],
)
def test_rejects_nonlocal_or_ambiguous_paths(port):
    with pytest.raises(ValueError):
        gateway_transport(port)


@pytest.mark.asyncio
async def test_identify_before_send_and_deliver_remaining_lines(serial_pair):
    reader, writer, opener = serial_pair
    received: list[str] = []
    gateway = gateway_transport("/dev/serial/by-id/test", received.append)
    connecting = asyncio.create_task(gateway.async_connect())
    await spin_until(lambda: bool(writer.writes))
    assert writer.writes == [b"!I\r\n"]
    assert not gateway.is_connected
    with pytest.raises(ConnectionError):
        await gateway.async_send(" W --- 18:123456 21:123456 --:------ 22F1 003 000100")
    reader.feed_data(b"unverified radio traffic\r\n# 18:12")
    reader.feed_data(b"3456\r\nfirst frame\r\nsecond frame\n")
    assert await connecting == "18:123456"
    await spin_until(lambda: len(received) == 2)
    assert received == ["first frame", "second frame"]
    await gateway.async_send("RF COMMAND")
    assert writer.writes == [b"!I\r\n", b"RF COMMAND\r\n"]
    kwargs = opener.call_args.kwargs
    assert kwargs["baudrate"] == 115200
    assert kwargs["exclusive"] is True
    assert kwargs["dtr_on_open"] is transport.PinState.HIGH
    assert kwargs["dtr_on_close"] is transport.PinState.UNDEFINED
    await gateway.async_close()
    assert writer.closed
    assert not gateway.is_connected
    assert gateway.gateway_id is None


@pytest.mark.asyncio
async def test_wrong_gateway_closes_without_any_rf_write(serial_pair):
    reader, writer, _ = serial_pair
    gateway = gateway_transport("/dev/ttyACM0")
    reader.feed_data(b"# 18:000001\r\n")
    with pytest.raises(transport.GatewayIdentityError) as error:
        await gateway.async_connect()
    assert error.value.actual == "18:000001"
    assert error.value.expected == "18:123456"
    assert writer.writes == [b"!I\r\n"]
    assert writer.closed
    assert gateway.gateway_id is None


@pytest.mark.asyncio
async def test_probe_returns_identity_and_releases_port(serial_pair):
    reader, writer, _ = serial_pair
    reader.feed_data(b"# 18:000001\r\n")
    assert await transport.async_probe_port("/dev/ttyACM0") == "18:000001"
    assert writer.writes == [b"!I\r\n"]
    assert writer.closed


@pytest.mark.asyncio
async def test_unrestricted_probe_connection_cannot_transmit_on_wrong_gateway(serial_pair):
    reader, writer, _ = serial_pair
    reader.feed_data(b"# 18:000001\r\n")
    gateway = gateway_transport("/dev/ttyACM0", expected_gateway_id=None)
    await gateway.async_connect()
    with pytest.raises(ConnectionError):
        await gateway.async_send("RF COMMAND")
    assert writer.writes == [b"!I\r\n"]
    await gateway.async_close()


@pytest.mark.asyncio
async def test_explicitly_configured_gateway_id_can_send(serial_pair):
    reader, writer, _ = serial_pair
    reader.feed_data(b"# 18:000001\r\n")
    gateway = gateway_transport("/dev/ttyACM0", expected_gateway_id="18:000001")
    await gateway.async_connect()
    await gateway.async_send("RF COMMAND")
    assert writer.writes == [b"!I\r\n", b"RF COMMAND\r\n"]
    await gateway.async_close()


@pytest.mark.asyncio
async def test_probe_timeout_closes(serial_pair, monkeypatch):
    _, writer, _ = serial_pair
    monkeypatch.setattr(transport, "PROBE_TIMEOUT", 0.01)
    with pytest.raises(TimeoutError):
        await transport.async_probe_port("/dev/ttyACM0")
    assert writer.closed
    assert writer.writes == [b"!I\r\n"]


@pytest.mark.asyncio
async def test_concurrent_connect_is_one_open_and_one_probe(serial_pair):
    reader, writer, opener = serial_pair
    gateway = gateway_transport("/dev/ttyACM0")
    first = asyncio.create_task(gateway.async_connect())
    second = asyncio.create_task(gateway.async_connect())
    await spin_until(lambda: bool(writer.writes))
    reader.feed_data(b"# 18:123456\r\n")
    assert await asyncio.gather(first, second) == ["18:123456", "18:123456"]
    opener.assert_awaited_once()
    assert writer.writes == [b"!I\r\n"]
    await gateway.async_close()


@pytest.mark.asyncio
async def test_close_cancels_pending_probe_and_is_idempotent(serial_pair):
    _, writer, _ = serial_pair
    gateway = gateway_transport("/dev/ttyACM0")
    task = asyncio.create_task(gateway.async_connect())
    await spin_until(lambda: bool(writer.writes))
    await gateway.async_close()
    with pytest.raises(asyncio.CancelledError):
        await task
    await gateway.async_close()
    assert writer.closed
    assert gateway._reader_task is None
    assert gateway._connect_task is None


@pytest.mark.asyncio
async def test_cancel_connect_releases_open_writer(serial_pair):
    _, writer, _ = serial_pair
    gateway = gateway_transport("/dev/ttyACM0")
    task = asyncio.create_task(gateway.async_connect())
    await spin_until(lambda: bool(writer.writes))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert writer.closed
    assert not gateway.is_connected


@pytest.mark.asyncio
async def test_eof_notifies_once_and_reconnect_reprobes(serial_pair, monkeypatch):
    reader, writer, opener = serial_pair
    disconnected = Mock()
    gateway = gateway_transport("/dev/ttyACM0", on_disconnect=disconnected)
    reader.feed_data(b"# 18:123456\r\n")
    await gateway.async_connect()
    reader.feed_eof()
    await spin_until(lambda: disconnected.call_count == 1)
    assert isinstance(disconnected.call_args.args[0], ConnectionError)
    assert not gateway.is_connected
    assert writer.closed
    with pytest.raises(ConnectionError):
        await gateway.async_send("RF COMMAND")
    next_reader, next_writer = asyncio.StreamReader(), FakeWriter()
    opener.return_value = (next_reader, next_writer)
    next_reader.feed_data(b"# 18:123456\r\n")
    await gateway.async_connect()
    assert next_writer.writes == [b"!I\r\n"]
    assert gateway.is_connected
    await gateway.async_close()
    assert disconnected.call_count == 1


@pytest.mark.asyncio
async def test_read_failure_clears_identity_and_closes(serial_pair):
    reader, writer, _ = serial_pair
    disconnected = Mock()
    gateway = gateway_transport("/dev/ttyACM0", on_disconnect=disconnected)
    reader.feed_data(b"# 18:123456\r\n")
    await gateway.async_connect()
    failure = OSError("USB unplugged")
    reader.set_exception(failure)
    await spin_until(lambda: disconnected.called)
    disconnected.assert_called_once_with(failure)
    assert writer.closed
    assert gateway.gateway_id is None


@pytest.mark.asyncio
async def test_overlong_and_non_ascii_lines_resynchronize(serial_pair):
    reader, _, _ = serial_pair
    received: list[str] = []
    gateway = gateway_transport("/dev/ttyACM0", received.append)
    reader.feed_data(b"# 18:123456\r\n")
    await gateway.async_connect()
    reader.feed_data(b"x" * (transport.MAX_LINE_BYTES + 20))
    reader.feed_data(b"plausible suffix\r\n\xffbad\ncontrol\x00line\nvalid\r\n")
    await spin_until(lambda: bool(received))
    assert received == ["valid"]
    await gateway.async_close()


@pytest.mark.asyncio
async def test_unterminated_line_is_not_delivered_on_eof(serial_pair):
    reader, _, _ = serial_pair
    received: list[str] = []
    disconnected = Mock()
    gateway = gateway_transport("/dev/ttyACM0", received.append, disconnected)
    reader.feed_data(b"# 18:123456\r\n")
    await gateway.async_connect()
    reader.feed_data(b"incomplete radio frame")
    reader.feed_eof()
    await spin_until(lambda: disconnected.called)
    assert received == []


@pytest.mark.parametrize("command", ["", "!B", " !I", "frame\r\n!B", "RF\x00", "RF€", "x" * 513])
@pytest.mark.asyncio
async def test_command_injection_and_bounds_rejected(serial_pair, command):
    reader, writer, _ = serial_pair
    reader.feed_data(b"# 18:123456\r\n")
    gateway = gateway_transport("/dev/ttyACM0")
    await gateway.async_connect()
    with pytest.raises(ValueError):
        await gateway.async_send(command)
    assert writer.writes == [b"!I\r\n"]
    await gateway.async_close()


@pytest.mark.asyncio
async def test_write_timeout_drops_connection_and_never_retries(serial_pair, monkeypatch):
    reader, writer, _ = serial_pair
    disconnected = Mock()
    reader.feed_data(b"# 18:123456\r\n")
    gateway = gateway_transport("/dev/ttyACM0", on_disconnect=disconnected)
    await gateway.async_connect()
    writer.drain.side_effect = asyncio.Event().wait
    monkeypatch.setattr(transport, "WRITE_TIMEOUT", 0.01)
    with pytest.raises(TimeoutError):
        await gateway.async_send("RF COMMAND")
    assert writer.writes == [b"!I\r\n", b"RF COMMAND\r\n"]
    assert writer.closed
    assert not gateway.is_connected
    assert disconnected.call_count == 1


@pytest.mark.asyncio
async def test_stuck_close_is_aborted(serial_pair, monkeypatch):
    reader, writer, _ = serial_pair
    reader.feed_data(b"# 18:123456\r\n")
    gateway = gateway_transport("/dev/ttyACM0")
    await gateway.async_connect()
    writer.wait_closed.side_effect = asyncio.Event().wait
    monkeypatch.setattr(transport, "CLOSE_TIMEOUT", 0.01)
    await gateway.async_close()
    assert writer.transport.abort.called
    assert gateway._reader_task is None


@pytest.mark.asyncio
async def test_callback_exception_releases_connection(serial_pair):
    reader, writer, _ = serial_pair
    disconnected = Mock()
    reader.feed_data(b"# 18:123456\r\n")
    callback = Mock(side_effect=RuntimeError("bad consumer"))
    gateway = gateway_transport("/dev/ttyACM0", callback, disconnected)
    await gateway.async_connect()
    reader.feed_data(b"valid line\r\n")
    await spin_until(lambda: disconnected.called)
    assert writer.closed
    assert not gateway.is_connected


@pytest.mark.asyncio
async def test_shutdown_cancels_blocked_and_queued_sends(serial_pair):
    reader, writer, _ = serial_pair
    reader.feed_data(b"# 18:123456\r\n")
    gateway = gateway_transport("/dev/ttyACM0")
    await gateway.async_connect()
    writer.drain.side_effect = asyncio.Event().wait
    first = asyncio.create_task(gateway.async_send("FIRST FRAME"))
    second = asyncio.create_task(gateway.async_send("SECOND FRAME"))
    await spin_until(lambda: len(gateway._send_tasks) == 2)
    await gateway.async_close()
    assert first.cancelled()
    assert second.cancelled()
    assert writer.writes == [b"!I\r\n", b"FIRST FRAME\r\n"]
    assert not gateway._send_tasks


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform not in ("linux", "darwin"), reason="POSIX PTY test")
async def test_real_serialx_backend_with_software_pty():
    """Check actual serialx settings/locking without opening any USB device."""
    master, slave = os.openpty()
    os.set_blocking(master, False)
    loop = asyncio.get_running_loop()
    commands: list[bytes] = []
    pending = bytearray()

    def respond() -> None:
        pending.extend(os.read(master, 4096))
        while b"\r\n" in pending:
            command, _, remainder = pending.partition(b"\r\n")
            pending[:] = remainder
            commands.append(bytes(command))
            if command == b"!I":
                os.write(master, b"# 18:123456\r\n")

    loop.add_reader(master, respond)
    gateway = gateway_transport(os.ttyname(slave))
    other = gateway_transport(os.ttyname(slave))
    try:
        assert await gateway.async_connect() == "18:123456"
        with pytest.raises(OSError):
            await other.async_connect()
        await gateway.async_send("SOFTWARE TEST FRAME")
        await spin_until(lambda: len(commands) == 2)
        assert commands == [b"!I", b"SOFTWARE TEST FRAME"]
    finally:
        await other.async_close()
        await gateway.async_close()
        loop.remove_reader(master)
        os.close(master)
        os.close(slave)


async def test_transport_without_explicit_identity_is_probe_only(serial_pair):
    """Removing the personal default must never enable unverified RF sends."""
    reader, writer, _ = serial_pair
    reader.feed_data(b"# 18:123456\r\n")
    gateway = transport.GatewayTransport("/dev/ttyACM0")
    try:
        assert await gateway.async_connect() == "18:123456"
        with pytest.raises(ConnectionError, match="explicitly expected"):
            await gateway.async_send("W --- 18:123456 21:123456 --:------ 22F1 003 000100")
        assert writer.writes == [b"!I\r\n"]
    finally:
        await gateway.async_close()
