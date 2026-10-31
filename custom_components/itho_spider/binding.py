"""Bounded gateway association; never bind, impersonate, or command a relay."""

from .protocol import ALL_DEVICES, NO_DEVICE, Packet, validate_device_id


def address_hex(address: str) -> str:
    validate_device_id(address)
    device_type, serial = map(int, address.split(":"))
    return f"{(device_type << 18) | serial:06X}"


def is_gateway_offer(packet: Packet, spider_id: str) -> bool:
    """Match either gateway offer profile recorded on the two physical Spiders."""
    if packet.src != spider_id or packet.verb != "I" or packet.code != "1FC9":
        return False
    if not (
        (packet.dst == NO_DEVICE and packet.via == spider_id)
        or (packet.dst in {spider_id, ALL_DEVICES} and packet.via == NO_DEVICE)
    ):
        return False
    data = packet.payload
    if not data or len(data) % 6:
        return False
    tuples = [data[i : i + 6] for i in range(0, len(data), 6)]
    own = bytes.fromhex(address_hex(spider_id))
    profiles = (
        ("0022C9", "003110", "0022F1", "023EF0", "0110E0", "001FC9"),
        ("0022C9", "0022F1", "00000E", "0110E0", "001FC9"),
    )
    return (
        all(item[3:] == own for item in tuples)
        and tuple(item[:3].hex().upper() for item in tuples) in profiles
    )


def gateway_accept(spider_id: str, gateway_id: str) -> str:
    validate_device_id(spider_id, 21)
    validate_device_id(gateway_id, 18)
    return f"W --- {gateway_id} {spider_id} {NO_DEVICE} 1FC9 006 0001FF{address_hex(gateway_id)}"


def is_confirmation(packet: Packet, spider_id: str, gateway_id: str) -> bool:
    return (
        packet.src == spider_id
        and packet.dst == gateway_id
        and packet.via == NO_DEVICE
        and packet.verb == "I"
        and packet.code == "1FC9"
        and packet.payload == b"\x00"
    )
