"""P116 R39 focused tests — official-app phone capture documentation closure.

Offline only. No network, no sockets, no device contact, no listener interaction.
The raw PCAP is deliberately NOT part of the repository: the tests exercise the parser on
synthetic LINKTYPE=101 captures built in memory and assert the committed safe-scalar fixture
and the documentation invariants.
"""

from __future__ import annotations

import importlib.util
import json
import re
import struct
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = TESTS_DIR.parent / "research" / "media" / "v1"
FIXTURE_PATH = TESTS_DIR / "fixtures" / "p116_r39_phone_capture_scalars.json"
MODEL_PATH = RESEARCH_DIR / "entrance_p116_r39_phone_capture_trace_model.py"
REPORT_PATH = RESEARCH_DIR / "P116_R39_OFFICIAL_APP_PHONE_CAPTURE.md"
PLAN_PATH = RESEARCH_DIR / "P116_R40_OFFICIAL_APP_READINESS_OFFLINE_PLAN.md"

PCAP_MAGIC_US_LE = b"\xd4\xc3\xb2\xa1"
IPV4_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def _load_model():
    spec = importlib.util.spec_from_file_location("p116_r39_trace_model", MODEL_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise AssertionError("trace model not importable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODEL = _load_model()


def _ipv4_header(proto: int, src: bytes, dst: bytes, payload_len: int) -> bytes:
    total = 20 + payload_len
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        total,
        0,
        0,
        64,
        proto,
        0,
        src,
        dst,
    )
    return header


def _udp_payload(sport: int, dport: int, payload: bytes) -> bytes:
    return struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload


def _tcp_payload(sport: int, dport: int, flags: int, payload: bytes = b"") -> bytes:
    header = struct.pack("!HHIIBBHHH", sport, dport, 1, 1, 0x50, flags, 8192, 0, 0)
    return header + payload


def _build_capture(packets: list[tuple[float, bytes]]) -> bytes:
    out = bytearray(PCAP_MAGIC_US_LE)
    out += struct.pack("<HHiIII", 2, 4, 0, 0, 32768, 101)
    for ts, packet in packets:
        seconds = int(ts)
        micros = int(round((ts - seconds) * 1_000_000))
        out += struct.pack("<IIII", seconds, micros, len(packet), len(packet))
        out += packet
    return bytes(out)


class SyntheticTraceTests(unittest.TestCase):
    """Parser behaviour on synthetic raw-IP captures."""

    def setUp(self) -> None:
        self.client = bytes([10, 0, 0, 5])
        self.remote = bytes([10, 0, 0, 9])
        packets = [
            (1.0, _ipv4_header(17, self.client, self.remote, 12) + _udp_payload(40000, 3478, b"stun")),
            (1.5, _ipv4_header(17, self.remote, self.client, 12) + _udp_payload(3478, 40000, b"stun")),
            (2.0, _ipv4_header(6, self.client, self.remote, 20) + _tcp_payload(41000, 443, 0x02)),
            (2.4, _ipv4_header(6, self.remote, self.client, 20) + _tcp_payload(443, 41000, 0x12)),
            (3.0, _ipv4_header(6, self.client, self.remote, 24) + _tcp_payload(41000, 443, 0x18, b"tls")),
        ]
        self.blob = _build_capture(packets)

    def test_parses_synthetic_raw_ip_capture(self) -> None:
        header, records = MODEL.iter_records(self.blob)
        self.assertEqual(header["linktype"], 101)
        self.assertEqual(len(records), 5)
        summary = MODEL.analyze(records, header)
        payload = MODEL.to_safe_dict(summary)
        MODEL.assert_safe_summary(payload)
        self.assertEqual(payload["packet_count"], 5)
        self.assertEqual(payload["protocol_counts"], {"TCP": 3, "UDP": 2})
        self.assertEqual(payload["peer_count"], 1)
        self.assertEqual(payload["outbound_packets"], 3)
        self.assertEqual(payload["inbound_packets"], 2)
        self.assertEqual(payload["duration_seconds"], 2.0)
        self.assertEqual(payload["transport_categories"]["STUN"], 2)
        self.assertEqual(payload["transport_categories"]["TCP_443_TLS_LIKE"], 3)

    def test_direction_roles_are_explicit(self) -> None:
        header, records = MODEL.iter_records(self.blob)
        payload = MODEL.to_safe_dict(MODEL.analyze(records, header))
        directions = {flow["direction"] for flow in payload["flows"]}
        self.assertEqual(directions, {"CLIENT_TO_REMOTE", "REMOTE_TO_CLIENT"})
        for flow in payload["flows"]:
            self.assertRegex(flow["remote_alias"], r"^R\d+$")

    def test_tcp_flags_are_counted(self) -> None:
        header, records = MODEL.iter_records(self.blob)
        payload = MODEL.to_safe_dict(MODEL.analyze(records, header))
        tcp_flows = [flow for flow in payload["flows"] if flow["protocol"] == "TCP"]
        self.assertTrue(tcp_flows)
        syn_total = sum(flow["tcp_flags"]["syn"] for flow in tcp_flows)
        self.assertEqual(syn_total, 2)

    def test_keepalive_candidate_port_is_categorised(self) -> None:
        packets = [
            (1.0, _ipv4_header(17, self.client, self.remote, 4) + _udp_payload(44766, 28450, b"")),
        ]
        header, records = MODEL.iter_records(_build_capture(packets))
        payload = MODEL.to_safe_dict(MODEL.analyze(records, header))
        self.assertEqual(payload["transport_categories"], {"UDP_KEEPALIVE_CANDIDATE": 1})

    def test_nanosecond_header_is_supported(self) -> None:
        blob = bytearray(b"\x4d\x3c\xb2\xa1") + bytearray(struct.pack("<HHiIII", 2, 4, 0, 0, 32768, 101))
        packet = _ipv4_header(17, self.client, self.remote, 8) + _udp_payload(1, 53, b"")
        blob += struct.pack("<IIII", 1, 500, len(packet), len(packet)) + packet
        payload = MODEL.summarise_capture_bytes(bytes(blob)) if hasattr(MODEL, "summarise_capture_bytes") else None
        if payload is None:  # pragma: no cover - helper optional
            header, records = MODEL.iter_records(bytes(blob))
            payload = MODEL.to_safe_dict(MODEL.analyze(records, header))
        self.assertEqual(payload["timestamp_resolution"], "nanosecond")
        self.assertEqual(payload["packet_count"], 1)


class FailClosedTests(unittest.TestCase):
    """Malformed or unsupported input must fail closed, never guess."""

    def test_pcapng_is_rejected(self) -> None:
        with self.assertRaises(MODEL.PcapParseError):
            MODEL.iter_records(b"\x0a\x0d\x0d\x0a" + b"\x00" * 40)

    def test_unsupported_linktype_is_rejected(self) -> None:
        blob = bytearray(PCAP_MAGIC_US_LE)
        blob += struct.pack("<IHHiIII", 2, 4, 0, 0, 0, 32768, 1)
        with self.assertRaises(MODEL.PcapParseError):
            MODEL.iter_records(bytes(blob))

    def test_truncated_header_is_rejected(self) -> None:
        with self.assertRaises(MODEL.PcapParseError):
            MODEL.iter_records(b"\xd4\xc3\xb2\xa1" + b"\x00" * 8)

    def test_truncated_payload_is_rejected(self) -> None:
        blob = bytearray(PCAP_MAGIC_US_LE)
        blob += struct.pack("<IHHiIII", 2, 4, 0, 0, 0, 32768, 101)
        blob += struct.pack("<IIII", 1, 0, 60, 60) + b"\x45" * 10
        with self.assertRaises(MODEL.PcapParseError):
            MODEL.iter_records(bytes(blob))

    def test_empty_capture_is_rejected(self) -> None:
        blob = PCAP_MAGIC_US_LE + struct.pack("<IHHiIII", 2, 4, 0, 0, 0, 32768, 101)
        with self.assertRaises(MODEL.PcapParseError):
            MODEL.iter_records(blob)


class PrivacyInvariantTests(unittest.TestCase):
    """No addresses, hexdumps or credential-like tokens may survive rendering."""

    def test_safe_summary_rejects_address_leak(self) -> None:
        with self.assertRaises(MODEL.PcapParseError):
            MODEL.assert_safe_summary({"peer": "10.0.0.5"})

    def test_safe_summary_rejects_hexdump_leak(self) -> None:
        with self.assertRaises(MODEL.PcapParseError):
            MODEL.assert_safe_summary({"payload": "de ad be ef 01 02 03 04 05 06 07 08"})

    def test_safe_summary_rejects_credential_like_token(self) -> None:
        with self.assertRaises(MODEL.PcapParseError):
            MODEL.assert_safe_summary({"note": "bearer value"})

    def test_rendered_summary_of_synthetic_trace_is_leak_free(self) -> None:
        client = bytes([172, 16, 30, 4])
        remote = bytes([172, 16, 30, 9])
        packets = [
            (1.0, _ipv4_header(6, client, remote, 20) + _tcp_payload(50000, 443, 0x18, b"\xde\xad\xbe\xef")),
        ]
        header, records = MODEL.iter_records(_build_capture(packets))
        rendered = json.dumps(MODEL.to_safe_dict(MODEL.analyze(records, header)), sort_keys=True)
        self.assertIsNone(IPV4_RE.search(rendered))
        self.assertNotIn("deadbeef", rendered.replace(" ", ""))

    def test_parser_has_no_network_surface(self) -> None:
        source = MODEL_PATH.read_text(encoding="utf-8")
        for forbidden in ("import socket", "import requests", "urllib", "http.client", "subprocess", "asyncio"):
            self.assertNotIn(forbidden, source)


class FixtureTests(unittest.TestCase):
    """The committed safe-scalar fixture is complete, safe and structurally consistent."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_fixture_declares_raw_capture_not_committed(self) -> None:
        provenance = self.fixture["fixture_provenance"]
        self.assertFalse(provenance["raw_capture_committed"])
        self.assertEqual(
            provenance["raw_capture_sha256"],
            "5d3733e2a41e3b175ffb4dd93373a758deae25c9a8247a43e47cff3d5fa0c8f9",
        )
        self.assertEqual(provenance["raw_capture_bytes"], 228129)

    def test_fixture_capture_expectations_match_parser_categories(self) -> None:
        expectations = self.fixture["capture_expectations"]
        self.assertEqual(expectations["linktype"], 101)
        self.assertEqual(expectations["packet_count"], 901)
        self.assertEqual(expectations["protocol_counts"], {"TCP": 661, "UDP": 240})
        self.assertEqual(expectations["peer_count"], 8)
        self.assertEqual(expectations["duration_seconds"], 258.28)
        self.assertEqual(
            sorted(expectations["transport_categories"]),
            sorted(expectations["expected_category_keys"]),
        )
        self.assertEqual(sum(expectations["protocol_counts"].values()), 901)
        self.assertEqual(
            sum(expectations["transport_categories"].values()),
            901,
        )

    def test_fixture_records_absence_of_ring_in_capture(self) -> None:
        expectations = self.fixture["capture_expectations"]
        self.assertFalse(expectations["ring_present_in_capture"])
        self.assertFalse(expectations["call_init_present_in_capture"])
        self.assertFalse(expectations["first_rtp_present_in_capture"])
        result = self.fixture["r39_result_scalars"]
        self.assertEqual(
            result["R39_RESULT_DETAIL"],
            "OFFICIAL_APP_NOT_READY_AND_RING_OUTSIDE_CAPTURE_WINDOW",
        )
        self.assertEqual(result["REQUIRED_OPERATOR_ACTION"], "NONE_DURING_CAPTURE")
        self.assertEqual(result["NEW_ICE_AFTER_CALL_INIT"], "UNPROVEN")
        self.assertFalse(result["RAW_PCAP_COMMITTED"])
        self.assertFalse(result["NEXT_LIVE_AUTHORIZED"])

    def test_fixture_door_followup_split(self) -> None:
        door = self.fixture["door_followup_scalars"]
        self.assertEqual(door["RESEARCH_DOOR_ACTIONS"], 0)
        self.assertEqual(door["DOOR_ACTIONS_BY_R39"], 0)
        self.assertEqual(door["OPERATOR_DOOR_ACTIONS"], 2)
        self.assertEqual(door["MACHINE_DOOR_OPERATION_COUNT"], 2)
        self.assertEqual(door["DOOR_PROTOCOL_ACKED_COUNT"], 0)
        self.assertEqual(door["DOOR_PHYSICAL_OPEN_REPORTED_COUNT"], 0)
        self.assertFalse(door["AUTOMATIC_DOOR_RETRY"])
        self.assertEqual(door["DOOR_READY_RACE"], "WEAKENED")
        self.assertEqual(door["DOOR_ROOT_CAUSE"], "UNRESOLVED")

    def test_fixture_is_address_free(self) -> None:
        rendered = json.dumps(self.fixture, sort_keys=True)
        self.assertIsNone(IPV4_RE.search(rendered))

    def test_fixture_lifecycle_claims_are_consistent(self) -> None:
        lifecycle = self.fixture["listener_lifecycle_scalars"]
        self.assertTrue(lifecycle["LISTENER_READY_AFTER"])
        self.assertTrue(lifecycle["LISTENER_RUNNING_AFTER"])
        self.assertFalse(lifecycle["FAILSAFE_TRIGGERED"])
        self.assertEqual(lifecycle["HA_RESTARTS"], 0)
        self.assertEqual(lifecycle["DEPLOYS"], 0)
        self.assertTrue(lifecycle["RING_BUDGET_CONSUMED"])
        self.assertEqual(lifecycle["PHYSICAL_RING_COUNT"], lifecycle["PHYSICAL_RING_BUDGET"])


class ReportInvariantTests(unittest.TestCase):
    """The canonical R39 report and the offline R40 plan satisfy their contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.report = REPORT_PATH.read_text(encoding="utf-8")
        cls.plan = PLAN_PATH.read_text(encoding="utf-8")

    def test_report_contains_canonical_blocks(self) -> None:
        self.assertIn("=== COMELIT P116 R39 OFFICIAL APP PHONE CAPTURE ===", self.report)
        self.assertIn("=== END COMELIT P116 R39 OFFICIAL APP PHONE CAPTURE ===", self.report)
        self.assertIn("=== COMELIT R39 CORRECTIVE / DOOR FORENSIC ===", self.report)
        self.assertIn("=== END COMELIT R39 CORRECTIVE / DOOR FORENSIC ===", self.report)

    def test_report_has_no_ambiguous_standalone_door_actions_line(self) -> None:
        for line in self.report.splitlines():
            self.assertNotEqual(line.strip(), "DOOR_ACTIONS=0")

    def test_report_carries_the_split_door_fields(self) -> None:
        for field in (
            "RESEARCH_DOOR_ACTIONS=0",
            "DOOR_ACTIONS_BY_R39=0",
            "OPERATOR_DOOR_ACTIONS=2",
            "OPERATOR_DOOR_BUTTON_PRESSES_REPORTED=2",
            "OPERATOR_DOOR_ACTION_SOURCE=manual",
            "OPERATOR_DOOR_AUTOMATION=false",
            "MACHINE_DOOR_OPERATION_COUNT=2",
            "UNIQUE_DOOR_OPERATION_IDS=2",
            "V4_DOOR_RESULT_COUNT=2",
            "TWO_RESULT_LINES_EQUAL_TWO_OPERATIONS=PROVEN",
            "DOOR_PROTOCOL_ACKED_COUNT=0",
            "DOOR_PHYSICAL_OPEN_REPORTED_COUNT=0",
            "AUTOMATIC_DOOR_RETRY=false",
            "DOOR_READY_RACE=WEAKENED",
        ):
            self.assertIn(field, self.report)

    def test_report_states_result_detail_without_answer_claim(self) -> None:
        self.assertIn("R39_RESULT_DETAIL=OFFICIAL_APP_NOT_READY_AND_RING_OUTSIDE_CAPTURE_WINDOW", self.report)
        self.assertIn("REQUIRED_OPERATOR_ACTION=NONE_DURING_CAPTURE", self.report)
        lowered = self.report.lower()
        self.assertIn("no answer/video button was required", lowered)
        self.assertIn("no such event occurred", lowered)

    def test_report_has_door_followup_section_and_no_fix_claim(self) -> None:
        self.assertIn("DOOR FOLLOW-UP", self.report)
        self.assertIn("root cause", self.report.lower())
        self.assertIn("unresolved", self.report.lower())
        self.assertIn("no new door test was run", self.report.lower())

    def test_report_has_no_raw_pcap_and_declares_it(self) -> None:
        self.assertIn("RAW_PCAP_COMMITTED=false", self.report)
        self.assertIn("5d3733e2a41e3b175ffb4dd93373a758deae25c9a8247a43e47cff3d5fa0c8f9", self.report)

    def test_report_and_plan_are_address_free(self) -> None:
        for text in (self.report, self.plan):
            matches = [m for m in IPV4_RE.findall(text) if m not in {"2.4", "0.0.0.0"}]
            self.assertEqual(matches, [])

    def test_plan_keeps_next_live_unauthorized(self) -> None:
        self.assertIn("NEXT_LIVE_AUTHORIZED=false", self.plan)
        self.assertIn("OFFICIAL_APP_READY", self.plan)
        self.assertIn("UNPROVEN", self.plan)
        self.assertIn("PCAPdroid", self.plan)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
