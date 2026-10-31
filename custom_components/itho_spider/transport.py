"""Bounded, identity-checked local USB transport for the evofw3 gateway.

This module has no Home Assistant dependency. The coordinator owns reconnect
policy: a lost connection closes the port, clears identity, and invokes the
synchronous disconnect callback once. A new connection always sends a fresh
local ``!I`` probe before accepting RF commands. Nothing is retried on the wire.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from pathlib import PurePosixPath

from serialx import Parity, PinState, StopBits, open_serial_connection

_LOGGER = logging.getLogger(__name__)

BAUDRATE = 115200
MAX_LINE_BYTES = 1024
MAX_COMMAND_BYTES = 512
READ_CHUNK_BYTES = 512
CONNECT_TIMEOUT = 5.0
PROBE_TIMEOUT = 5.0
WRITE_TIMEOUT = 2.0
CLOSE_TIMEOUT = 2.0
_IDENTITY_RE = re.compile(r"#\s+(\d{2}:\d{6})\s*")

type LineCallback = Callable[[str], None]
type DisconnectCallback = Callable[[Exception | None], None]


class GatewayIdentityError(ValueError):
    """The connected gateway does not have the expected radio identity."""

    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Expected gateway {expected}, received {actual}")


def validate_port(port: str) -> str:
    """Accept a local POSIX device path, never a serial proxy URL."""
    if (
        not isinstance(port, str)
        or not port.startswith("/dev/")
        or port.endswith("/")
        or ".." in PurePosixPath(port).parts
        or any(ord(char) < 32 or ord(char) == 127 for char in port)
        or any(marker in port for marker in ("://", "?", "#", "\\"))
    ):
        raise ValueError("Choose an absolute local serial device path under /dev/")
    return port


async def _iter_lines(reader: asyncio.StreamReader) -> AsyncIterator[str]:
    """Yield printable ASCII lines; discard oversized/malformed frames fully."""
    pending = bytearray()
    discarding = False
    while chunk := await reader.read(READ_CHUNK_BYTES):
        for byte in chunk:
            if byte == 10:
                if not discarding:
                    line = bytes(pending).removesuffix(b"\r")
                    if line and all(32 <= item <= 126 for item in line):
                        yield line.decode("ascii")
                pending.clear()
                discarding = False
            elif not discarding:
                pending.append(byte)
                if len(pending) > MAX_LINE_BYTES:
                    pending.clear()
                    discarding = True
    # An unterminated fragment on EOF is never delivered as a complete frame.


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    """Close without allowing a stuck serial driver to block shutdown."""
    writer.close()
    try:
        async with asyncio.timeout(CLOSE_TIMEOUT):
            await writer.wait_closed()
    except OSError, TimeoutError:
        writer.transport.abort()
    except asyncio.CancelledError:
        writer.transport.abort()
        raise


class GatewayTransport:
    """One serial connection with callbacks on the owning asyncio event loop.

    Callbacks must be synchronous and quick (for example ``queue.put_nowait``).
    ``expected_gateway_id=None`` is for identification only and disables RF
    sends. The caller must close the connection.
    """

    def __init__(
        self,
        port: str,
        on_line: LineCallback | None = None,
        on_disconnect: DisconnectCallback | None = None,
        *,
        expected_gateway_id: str | None = None,
    ) -> None:
        self.port = validate_port(port)
        self._on_line = on_line
        self._on_disconnect = on_disconnect
        self._expected_gateway_id = expected_gateway_id
        self._writer: asyncio.StreamWriter | None = None
        self._connect_task: asyncio.Task[str] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._send_tasks: set[asyncio.Task[None]] = set()
        self._write_lock = asyncio.Lock()
        self._closing = False
        self._disconnect_reported = False
        self.gateway_id: str | None = None

    @property
    def is_connected(self) -> bool:
        """Whether this connection has completed its own identity probe."""
        return self._writer is not None and self.gateway_id is not None

    async def async_connect(self) -> str:
        """Open and identify this port; only the local ``!I`` command is sent."""
        if self.is_connected:
            assert self.gateway_id is not None
            return self.gateway_id
        if self._connect_task is None:
            self._closing = False
            self._disconnect_reported = False
            self._connect_task = asyncio.create_task(
                self._connect(), name="itho_spider_serial_connect"
            )
        task = self._connect_task
        try:
            return await task
        finally:
            if self._connect_task is task and task.done():
                self._connect_task = None

    async def _connect(self) -> str:
        writer: asyncio.StreamWriter | None = None
        handed_over = False
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                reader, writer = await open_serial_connection(
                    url=self.port,
                    baudrate=BAUDRATE,
                    byte_size=8,
                    parity=Parity.NONE,
                    stopbits=StopBits.ONE,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                    exclusive=True,
                    dtr_on_open=PinState.HIGH,
                    rts_on_open=PinState.UNDEFINED,
                    dtr_on_close=PinState.UNDEFINED,
                    rts_on_close=PinState.UNDEFINED,
                )
            lines = _iter_lines(reader)
            async with asyncio.timeout(PROBE_TIMEOUT):
                writer.write(b"!I\r\n")
                await writer.drain()
                async for line in lines:
                    if match := _IDENTITY_RE.fullmatch(line):
                        actual = match.group(1)
                        break
                else:
                    raise ConnectionError("Serial port closed before gateway identification")
            if self._expected_gateway_id is not None and actual != self._expected_gateway_id:
                raise GatewayIdentityError(self._expected_gateway_id, actual)
            self.gateway_id = actual
            self._writer = writer
            self._reader_task = asyncio.create_task(
                self._read_loop(lines, writer), name="itho_spider_serial_reader"
            )
            handed_over = True
            return actual
        finally:
            if writer is not None and not handed_over:
                await _close_writer(writer)

    async def _read_loop(self, lines: AsyncIterator[str], writer: asyncio.StreamWriter) -> None:
        error: Exception | None = None
        try:
            async for line in lines:
                if self._on_line is not None:
                    self._on_line(line)
            error = ConnectionError("Serial device disconnected")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # Callback errors also close, instead of leaking a task.
            error = exc
        finally:
            if self._writer is writer:
                self._writer = None
                self.gateway_id = None
            await _close_writer(writer)
            if self._reader_task is asyncio.current_task():
                self._reader_task = None
            if not self._closing and error is not None:
                self._notify_disconnect(error)

    def _notify_disconnect(self, error: Exception) -> None:
        if self._disconnect_reported:
            return
        self._disconnect_reported = True
        if self._on_disconnect is not None:
            try:
                self._on_disconnect(error)
            except Exception:
                _LOGGER.exception("Serial disconnect callback failed")

    async def async_send(self, command: str) -> None:
        """Send one RF command after identification; never retry an uncertain send.

        The coordinator/protocol layer validates the RF message itself. Local
        debug/settings/bootloader commands are deliberately unavailable here.
        """
        if (
            not isinstance(command, str)
            or not command
            or len(command) > MAX_COMMAND_BYTES
            or "!" in command
            or any(not 32 <= ord(char) <= 126 for char in command)
        ):
            raise ValueError("Command must be one bounded printable ASCII RF frame")
        if not self.is_connected:
            raise ConnectionError("Gateway is not connected and identified")
        if self._expected_gateway_id is None:
            raise ConnectionError("RF sends require an explicitly expected gateway identity")
        if self.gateway_id != self._expected_gateway_id:
            raise GatewayIdentityError(self._expected_gateway_id, self.gateway_id or "unknown")
        task = asyncio.current_task()
        assert task is not None
        self._send_tasks.add(task)
        writer = self._writer
        try:
            async with asyncio.timeout(WRITE_TIMEOUT):
                async with self._write_lock:
                    writer = self._writer
                    if writer is None or self.gateway_id != self._expected_gateway_id:
                        raise ConnectionError("Gateway disconnected before send")
                    writer.write(command.encode("ascii") + b"\r\n")
                    await writer.drain()
        except asyncio.CancelledError:
            # A cancelled drain gives no delivery guarantee. Drop queued bytes
            # and require a new identification, never replay the command.
            if writer is not None and self._writer is writer:
                self._writer = None
                self.gateway_id = None
                writer.transport.abort()
                if self._reader_task is not None:
                    self._reader_task.cancel()
                if not self._closing:
                    self._notify_disconnect(ConnectionError("Serial send cancelled"))
            raise
        except (OSError, TimeoutError) as exc:
            await self.async_close()
            self._notify_disconnect(exc)
            raise
        finally:
            self._send_tasks.discard(task)

    async def async_close(self) -> None:
        """Cancel pending identification/reads and release the exclusive port."""
        self._closing = True
        self.gateway_id = None
        writer, self._writer = self._writer, None
        if writer is not None:
            writer.close()
        tasks = (self._connect_task, self._reader_task, *tuple(self._send_tasks))
        for task in tasks:
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        try:
            for task in tasks:
                if task is not None and task is not asyncio.current_task():
                    with suppress(asyncio.CancelledError, OSError, ValueError):
                        await task
            if writer is not None:
                await _close_writer(writer)
        finally:
            self._connect_task = None
            self._reader_task = None


async def async_probe_port(port: str) -> str:
    """Return the local gateway ID using only ``!I``, releasing the port afterward."""
    connection = GatewayTransport(port, expected_gateway_id=None)
    try:
        return await connection.async_connect()
    finally:
        await connection.async_close()
