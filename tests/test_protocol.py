"""Protocol regression tests; no Home Assistant, serial device or network needed."""

import importlib.util
import sys
import unittest
from dataclasses import replace
from pathlib import Path

# Load only the pure module. Importing the HA integration package would require
# Home Assistant and defeat the purpose of these standalone protocol tests.
_PATH = Path(__file__).parents[1] / "custom_components/itho_spider/protocol.py"
_SPEC = importlib.util.spec_from_file_location("itho_spider_protocol_test", _PATH)
protocol = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = protocol
_SPEC.loader.exec_module(protocol)

SPIDER = "21:123456"
GATEWAY = "18:123456"
STATUS = "00802C2428D00080000A3C28400000810480800280FF80040040"


def packet(code, payload, verb="I", src=SPIDER, dst=protocol.NO_DEVICE, rssi="060"):
    via = src if dst == protocol.NO_DEVICE else protocol.NO_DEVICE
    line = f"{rssi} {verb} --- {src} {dst} {via} {code} {len(payload) // 2:03d} {payload}"
    result = protocol.parse_packet(line)
    assert result is not None, line
    return result


def receive(state, code, payload, **kwargs):
    received_at = kwargs.pop("received_at", 100.0)
    return protocol.update_state(
        state,
        packet(code, payload, **kwargs),
        SPIDER,
        GATEWAY,
        received_at=received_at,
    )


def manual_state():
    state = receive(protocol.SpiderState(), "01FF", STATUS, verb="RQ", dst=GATEWAY)
    return receive(state, "3110", "00000010")


class PacketTests(unittest.TestCase):
    def test_receive_and_timestamped_log(self):
        pkt = packet("30C9", "000843")
        self.assertEqual(pkt.payload, b"\x00\x08\x43")
        self.assertEqual(pkt.rssi, 60)
        self.assertEqual(pkt.src, SPIDER)
        self.assertIsNone(pkt.sequence)
        logged = protocol.parse_packet("2000-01-01T12:00:00.123456 " + pkt.raw)
        self.assertEqual(logged.payload_hex, "000843")

    def test_lowercase_payload_and_ascii_bytes(self):
        pkt = protocol.parse_packet(
            f"060 I 001 {SPIDER} --:------ {SPIDER} 1060 003 00ff01\r\n".encode()
        )
        self.assertEqual(pkt.payload_hex, "00FF01")
        self.assertEqual(pkt.sequence, 1)

    def test_noise_invalid_length_trailer_and_ids_are_rejected(self):
        valid = packet("30C9", "000843").raw
        bad_lines = [
            "",
            "# evofw3 0.7.1",
            "!I",
            b"\xff",
            "060 checksum error",
            valid.replace("003", "004"),
            valid + " * Checksum error",
            valid.replace("000843", "00084Z"),
            valid.replace(SPIDER, "21:999999"),
            valid.replace(SPIDER, "64:123456"),
            valid.replace("060 I", "060 B"),
            valid.replace("30C9", "XXXX"),
            valid.split(" ", 1)[1],
        ]
        for line in bad_lines:
            with self.subTest(line=line):
                self.assertIsNone(protocol.parse_packet(line))

    def test_id_validation_and_injection_rejection(self):
        self.assertEqual(protocol.validate_device_id(SPIDER, 21), SPIDER)
        for value in ["21:12345", "21:123456\r!ER", "21:262144", "64:000000", None]:
            with self.subTest(value=value), self.assertRaises(protocol.ProtocolError):
                protocol.validate_device_id(value)
        with self.assertRaises(protocol.ProtocolError):
            protocol.validate_device_id(GATEWAY, 21)

    def test_rssi_zero_is_not_itself_a_transmit_echo(self):
        pkt = packet("30C9", "000843", rssi="000")
        self.assertFalse(pkt.is_gateway_echo(GATEWAY))
        state = protocol.update_state(protocol.SpiderState(), pkt, SPIDER, GATEWAY)
        self.assertEqual(state.temperature, 21.15)


class StateTests(unittest.TestCase):
    def test_initial_state_has_no_temperature_or_mode_defaults(self):
        state = protocol.SpiderState()
        for value in (
            state.temperature,
            state.target_temperature,
            state.cooling_target,
            state.time_planning,
            state.operating_mode,
        ):
            self.assertIsNone(value)

    def test_actual_spider_01ff_status(self):
        state = receive(protocol.SpiderState(), "01FF", STATUS, verb="RQ", dst=GATEWAY)
        self.assertEqual(state.temperature, 22)
        self.assertEqual(state.target_temperature, 18)
        self.assertEqual(state.cooling_target, 20)
        self.assertFalse(state.time_planning)
        self.assertFalse(state.temp_adjusted)
        self.assertEqual(state.raw_01ff, bytes.fromhex(STATUS))
        self.assertEqual(state.last_01ff_at, 100)
        self.assertEqual(state.last_setpoint_at, 100)

    def test_22c9_keeps_inverted_bounds_and_local_manual_write(self):
        state = receive(manual_state(), "22C9", "00083407D001", verb="W", dst=GATEWAY)
        self.assertEqual(state.target_temperature, 21)
        self.assertEqual(state.cooling_target, 20)
        self.assertEqual(state.operating_mode, "heat")

    def test_nonzero_zone_context_does_not_change_spider_state(self):
        original = manual_state()
        for code, payload in [("22C9", "01083407D001"), ("30C9", "010843"), ("3110", "01004010")]:
            with self.subTest(code=code):
                self.assertIs(receive(original, code, payload), original)

    def test_other_devices_gateway_echoes_and_other_gateway_are_ignored(self):
        original = manual_state()
        for src, dst in [(GATEWAY, SPIDER), ("21:123458", GATEWAY), (SPIDER, "18:000001")]:
            updated = receive(original, "01FF", STATUS, verb="RP", src=src, dst=dst)
            self.assertIs(updated, original)

    def test_unsupported_message_or_wrong_payload_shape_does_not_refresh_state(self):
        original = manual_state()
        for code, payload, verb in [
            ("0008", "0000", "I"),
            ("30C9", "00", "I"),
            ("01FF", STATUS, "W"),
            ("30C9", "000843", "RQ"),
        ]:
            self.assertIs(receive(original, code, payload, verb=verb), original)

    def test_planning_and_override_flags_from_primary_fixtures(self):
        for flags, planning, adjusted in [
            ("90", True, False),
            ("B0", True, True),
            ("D0", False, False),
        ]:
            payload = STATUS[:10] + flags + STATUS[12:]
            state = receive(protocol.SpiderState(), "01FF", payload)
            self.assertIs(state.time_planning, planning)
            self.assertIs(state.temp_adjusted, adjusted)

    def test_sentinals_and_invalid_setpoints_clear_control_readiness(self):
        original = manual_state()
        for raw in ["7F", "80", "FF", "00", "08", "40"]:
            payload = STATUS[:6] + raw + STATUS[8:]
            state = receive(original, "01FF", payload)
            self.assertIsNone(state.target_temperature)
        state = receive(original, "22C9", "007FFF31FF01")
        self.assertIsNone(state.target_temperature)
        self.assertIsNone(state.cooling_target)

    def test_01ff_missing_second_bound(self):
        data = bytearray.fromhex(STATUS)
        data[11] = 0x80
        state = receive(manual_state(), "01FF", data.hex())
        self.assertIsNone(state.cooling_target)

    def test_precision_preference_expires(self):
        state = receive(protocol.SpiderState(), "30C9", "000843", received_at=100)
        state = receive(state, "01FF", STATUS, received_at=110)
        self.assertEqual(state.temperature, 21.15)
        self.assertEqual(state.display_temperature, 22)
        state = receive(state, "01FF", STATUS, received_at=281)
        self.assertEqual(state.temperature, 22)
        self.assertEqual(state.temperature_source, "01FF")

    def test_12c0_is_display_temperature_not_humidity(self):
        state = receive(protocol.SpiderState(), "12C0", "002901FF")
        self.assertEqual(state.display_temperature, 20.5)
        state = receive(state, "12C0", "004500FF")
        self.assertEqual(state.display_temperature, 20.56)
        state = receive(state, "12C0", "008001FF")
        self.assertIsNone(state.display_temperature)

    def test_demand_and_mode_are_separate_from_setpoint_freshness(self):
        state = receive(manual_state(), "3110", "00004010", received_at=200)
        self.assertEqual(state.demand, 0.32)
        self.assertEqual(state.heating_demand, 0.32)
        self.assertEqual(state.last_setpoint_at, 100)
        state = receive(state, "3110", "0000C820")
        self.assertEqual(state.operating_mode, "cool")
        self.assertEqual(state.demand, 1)
        self.assertIsNone(state.heating_demand)
        state = receive(state, "3110", "00000000")
        self.assertEqual(state.operating_mode, "off")
        self.assertIsNone(state.demand)

    def test_battery_boolean_and_unknown_percent(self):
        state = receive(protocol.SpiderState(), "1060", "00FF01")
        self.assertFalse(state.battery_low)
        self.assertIsNone(state.battery_percent)
        state = receive(state, "1060", "002800")
        self.assertTrue(state.battery_low)
        self.assertEqual(state.battery_percent, 20)
        state = receive(state, "1060", "000001")
        self.assertIsNone(state.battery_percent)


class CommandTests(unittest.TestCase):
    def test_local_heating_ack_preserves_both_fields(self):
        local = packet("22C9", "00083407D001", verb="W", dst=GATEWAY)
        self.assertEqual(
            protocol.build_local_setpoint_ack(local, SPIDER, GATEWAY),
            "I --- 18:123456 21:123456 --:------ 22C9 006 00083407D001\r",
        )

    def test_local_ack_rejects_unrelated_or_unsupported_commands(self):
        invalid = [
            packet("22D0", "00083407D001", verb="W", dst=GATEWAY),
            packet("22C9", "00083407D001", verb="W", dst="18:000001"),
            packet("22C9", "00083407D001", verb="I", dst=GATEWAY),
            packet("22C9", "00083407D001", verb="W"),
            packet("22C9", "00083407D001", verb="W", src="21:000001", dst=GATEWAY),
            packet("22C9", "01083407D001", verb="W", dst=GATEWAY),
            packet("22C9", "00083407D002", verb="W", dst=GATEWAY),
            packet("22C9", "0008347FFF01", verb="W", dst=GATEWAY),
        ]
        for pkt in invalid:
            with self.subTest(pkt=pkt), self.assertRaises(protocol.ProtocolError):
                protocol.build_local_setpoint_ack(pkt, SPIDER, GATEWAY)

    def test_known_blueprint_profile_retains_current_second_setpoint(self):
        state = manual_state()
        command = protocol.build_setpoint_command(SPIDER, GATEWAY, 21, state)
        self.assertEqual(
            command,
            "W --- 18:123456 21:123456 --:------ 01FF 026 "
            "0080802A28D0000000143C80800000B40080800280FF80040000\r",
        )
        self.assertEqual(state.target_temperature, 18)  # Not optimistic confirmation.
        reply = protocol.build_setpoint_command(SPIDER, GATEWAY, 18, state, verb="RP")
        self.assertEqual(
            reply,
            "RP --- 18:123456 21:123456 --:------ 01FF 026 "
            "0080802428D0000000143C80800000B40080800280FF80040000\r",
        )

    def test_no_default_write_before_learning_both_fields_and_manual_state(self):
        state = manual_state()
        invalid = [
            protocol.SpiderState(),
            replace(state, raw_01ff=None),
            replace(state, target_temperature=None),
            replace(state, cooling_target=None),
            replace(state, time_planning=None),
            replace(state, time_planning=True),
            replace(state, operating_mode="cool"),
            replace(state, operating_mode="off"),
            replace(state, raw_01ff=b"\x00" * 26),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(protocol.ProtocolError):
                protocol.build_setpoint_command(SPIDER, GATEWAY, 21, value)

    def test_invalid_targets_are_rejected_not_rounded_or_clamped(self):
        for value in [None, True, "21", 21.1, 4.5, 30.5, float("nan"), float("inf")]:
            with self.subTest(value=value), self.assertRaises(protocol.ProtocolError):
                protocol.build_setpoint_command(SPIDER, GATEWAY, value, manual_state())

    def test_configured_limits_and_verb_are_enforced(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.build_setpoint_command(
                SPIDER, GATEWAY, 17, manual_state(), min_temperature=18, max_temperature=24
            )
        with self.assertRaises(protocol.ProtocolError):
            protocol.build_setpoint_command(SPIDER, GATEWAY, 21, manual_state(), verb="RQ")
        with self.assertRaises(protocol.ProtocolError):
            protocol.build_setpoint_command(
                SPIDER, GATEWAY, 21, manual_state(), min_temperature=31, max_temperature=32
            )


if __name__ == "__main__":
    unittest.main()
