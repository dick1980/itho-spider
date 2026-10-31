"""Share one identified USB transport without competing serial readers."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable

from .protocol import parse_packet
from .transport import GatewayTransport

DATA_GATEWAYS = "itho_spider_gateway_pool"
MAX_SENDS_PER_MINUTE = 12


def get_gateway(pool: dict, port: str, gateway_id: str) -> SharedGateway:
    """Reuse the one active USB owner, including temporary setup wizard clients."""
    gateway = pool.get(port)
    if gateway is not None and gateway.gateway_id != gateway_id:
        if gateway._clients:
            raise ValueError("Serial port already belongs to a different gateway")
        gateway = None
    if gateway is None:
        gateway = pool[port] = SharedGateway(port, gateway_id)
    return gateway


class SharedGateway:
    """A single USB owner with per-thermostat, independently releasable leases."""

    def __init__(self, port: str, gateway_id: str) -> None:
        self.gateway_id = gateway_id
        self.port = port
        self._clients: set[GatewayClient] = set()
        self._lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._send_times: deque[float] = deque()
        self._transport = GatewayTransport(
            port, self._on_line, self._on_disconnect, expected_gateway_id=gateway_id
        )

    def client_factory(self, spider_id: str) -> Callable:
        def create(port, on_line, on_disconnect, *, expected_gateway_id):
            if port != self.port or expected_gateway_id != self.gateway_id:
                raise ValueError("Conflicting gateway identity or serial port")
            return GatewayClient(self, spider_id, on_line, on_disconnect)

        return create

    def _on_line(self, line: str) -> None:
        packet = parse_packet(line)
        if packet is None:
            return
        for client in tuple(self._clients):
            if packet.src == client.spider_id:
                client.on_line(line)

    def _on_disconnect(self, error: Exception | None) -> None:
        for client in tuple(self._clients):
            client.on_disconnect(error)


class GatewayClient:
    def __init__(self, gateway, spider_id, on_line, on_disconnect):
        self.gateway = gateway
        self.spider_id = spider_id
        self.on_line = on_line
        self.on_disconnect = on_disconnect

    @property
    def is_connected(self) -> bool:
        return self in self.gateway._clients and self.gateway._transport.is_connected

    async def async_connect(self) -> str:
        gateway = self.gateway
        async with gateway._lock:
            gateway._clients.add(self)
            try:
                if not gateway._transport.is_connected:
                    await gateway._transport.async_connect()
                if not gateway._transport.is_connected:
                    raise ConnectionError("Gateway disconnected while connecting")
            except BaseException:
                gateway._clients.discard(self)
                if not gateway._clients:
                    await gateway._transport.async_close()
                raise
        return gateway.gateway_id

    async def async_send(self, command: str) -> None:
        gateway = self.gateway
        packet = parse_packet("000 " + command)
        if (
            packet is None
            or packet.src != gateway.gateway_id
            or packet.dst != self.spider_id
            or packet.via != "--:------"
            or (packet.verb, packet.code)
            not in {("W", "01FF"), ("RP", "01FF"), ("I", "22C9"), ("W", "1FC9")}
        ):
            raise ValueError("Only this client's Spider may receive gateway commands")
        async with gateway._send_lock:
            if not self.is_connected:
                raise ConnectionError("Gateway client is disconnected")
            now = time.monotonic()
            while gateway._send_times and now - gateway._send_times[0] >= 60:
                gateway._send_times.popleft()
            if len(gateway._send_times) >= MAX_SENDS_PER_MINUTE:
                raise ConnectionError("Shared gateway radio rate limit reached")
            gateway._send_times.append(now)
            await gateway._transport.async_send(command)

    async def async_close(self) -> None:
        gateway = self.gateway
        async with gateway._lock:
            gateway._clients.discard(self)
            if not gateway._clients:
                await gateway._transport.async_close()
