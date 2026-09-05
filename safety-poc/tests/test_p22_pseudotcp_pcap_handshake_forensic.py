import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    ROOT
    / "safety-poc/research/media/v1/pseudotcp_pcap_handshake_forensic.py"
)

spec = importlib.util.spec_from_file_location("pseudotcp_pcap_handshake_forensic", MODULE_PATH)
assert spec and spec.loader
forensic = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = forensic
spec.loader.exec_module(forensic)


CLIENT_IP = bytes((10, 0, 0, 1))
DEVICE_IP = bytes((10, 0, 0, 2))
CLIENT_PORT = 41000
DEVICE_PORT = 42000


def pseudo(
    *,
    seq: int,
    ack: int,
    flags: int,
    data: bytes = b"",
    control: int = 0,
) -> bytes:
    return struct.pack(
        "!IIIBBHII",
        0,
        seq,
        ack,
        control,
        flags,
        65535,
        100,
        50,
    ) + data


def ipv4_udp(
    payload: bytes,
    *,
    source_ip: bytes,
    target_ip: bytes,
    source_port: int,
    target_port: int,
) -> bytes:
    udp_length = 8 + len(payload)
    udp = struct.pack("!HHHH", source_port, target_port, udp_length, 0) + payload
    total_length = 20 + len(udp)
    ipv4 = bytes((0x45, 0)) + struct.pack(
        "!HHHBBH4s4s",
        total_length,
        1,
        0,
        64,
        17,
        0,
        source_ip,
        target_ip,
    )
    return ipv4 + udp


def packet(payload: bytes, *, client_to_device: bool) -> bytes:
    if client_to_device:
        return ipv4_udp(
            payload,
            source_ip=CLIENT_IP,
            target_ip=DEVICE_IP,
            source_port=CLIENT_PORT,
            target_port=DEVICE_PORT,
        )
    return ipv4_udp(
        payload,
        source_ip=DEVICE_IP,
        target_ip=CLIENT_IP,
        source_port=DEVICE_PORT,
        target_port=CLIENT_PORT,
    )


def pcap(frames: list[bytes]) -> bytes:
    out = bytearray(
        struct.pack(
            "<IHHIIII",
            0xA1B2C3D4,
            2,
            4,
            0,
            0,
            65535,
            forensic.PCAP_LINKTYPE_RAW,
        )
    )
    for index, frame in enumerate(frames, start=1):
        out.extend(struct.pack("<IIII", 1000, index * 1000, len(frame), len(frame)))
        out.extend(frame)
    return bytes(out)


def normal_capture() -> bytes:
    ctl = forensic.PSEUDOTCP_FLAG_CTL
    return pcap(
        [
            packet(pseudo(seq=0, ack=0, flags=ctl, data=b"\x00" * 7), client_to_device=True),
            packet(pseudo(seq=0, ack=7, flags=ctl, data=b"\x00" * 7), client_to_device=False),
            packet(pseudo(seq=7, ack=7, flags=0), client_to_device=True),
            packet(
                pseudo(seq=7, ack=7, flags=0, data=b"\x00\x06\x0f\x00UAUT\x00"),
                client_to_device=True,
            ),
            packet(pseudo(seq=7, ack=18, flags=0), client_to_device=False),
        ]
    )


class P22PseudoTcpPcapHandshakeForensic(unittest.TestCase):
    def write_capture(self, blob: bytes) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".pcap", delete=False)
        tmp.write(blob)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        return Path(tmp.name)

    def test_header_layout_uses_flags_byte_13(self):
        payload = pseudo(seq=11, ack=22, flags=forensic.PSEUDOTCP_FLAG_RST, control=0xA5)
        parsed = forensic._pseudotcp_segment(
            1,
            0.0,
            forensic.Endpoint(CLIENT_IP, CLIENT_PORT),
            forensic.Endpoint(DEVICE_IP, DEVICE_PORT),
            payload,
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.control, 0xA5)
        self.assertEqual(parsed.flags, forensic.PSEUDOTCP_FLAG_RST)
        self.assertEqual(parsed.data_length, 0)
        self.assertEqual(forensic.flag_name(parsed.flags), "RST")

    def test_normal_client_initiated_handshake_is_proven(self):
        capture = forensic.load_capture(self.write_capture(normal_capture()))
        analysis = forensic.select_vip_flow(capture)
        text = forensic.report(capture, analysis, "synthetic", 10)

        self.assertIn("PSEUDOTCP_INITIATOR=CLIENT", text)
        self.assertIn("PSEUDOTCP_PRE_APP_RST_COUNT=0", text)
        self.assertIn("PSEUDOTCP_INITIAL_HANDSHAKE=PASS", text)
        self.assertIn("FIRST_CLIENT_CTL_PACKET=1", text)
        self.assertIn("FIRST_DEVICE_CTL_PACKET=2", text)
        self.assertIn("FIRST_CLIENT_ZERO_DATA_ACK_PACKET=3", text)
        self.assertIn("FIRST_APPLICATION_PACKET=4", text)

    def test_zero_length_rst_before_application_is_detected(self):
        ctl = forensic.PSEUDOTCP_FLAG_CTL
        rst = forensic.PSEUDOTCP_FLAG_RST
        blob = pcap(
            [
                packet(pseudo(seq=0, ack=0, flags=ctl, data=b"\x00" * 7), client_to_device=True),
                packet(pseudo(seq=0, ack=7, flags=rst), client_to_device=False),
                packet(
                    pseudo(seq=7, ack=0, flags=0, data=b"\x00\x06UAUT\x00"),
                    client_to_device=True,
                ),
            ]
        )
        capture = forensic.load_capture(self.write_capture(blob))
        analysis = forensic.select_vip_flow(capture)
        text = forensic.report(capture, analysis, "rst", 10)

        self.assertIn("PSEUDOTCP_PRE_APP_RST_COUNT=1", text)
        self.assertIn("PSEUDOTCP_TOTAL_RST_COUNT=1", text)
        self.assertIn("FIRST_RST_PACKET=2", text)
        self.assertIn("PSEUDOTCP_INITIAL_HANDSHAKE=NOT_PROVEN", text)
        self.assertIn("flags=RST data_len=0", text)

    def test_report_never_emits_endpoint_addresses_or_ports(self):
        capture = forensic.load_capture(self.write_capture(normal_capture()))
        analysis = forensic.select_vip_flow(capture)
        text = forensic.report(capture, analysis, "privacy", 10)

        for forbidden in (
            "10.0.0.1",
            "10.0.0.2",
            str(CLIENT_PORT),
            str(DEVICE_PORT),
            "UAUT",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("ENDPOINTS_EMITTED=false", text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)

    def test_non_raw_linktype_fails_closed(self):
        blob = bytearray(normal_capture())
        blob[20:24] = struct.pack("<I", 1)
        with self.assertRaisesRegex(ValueError, "unsupported linktype"):
            forensic.load_capture(self.write_capture(bytes(blob)))

    def test_ambiguous_or_unanchored_flow_fails_closed(self):
        blob = pcap(
            [
                packet(pseudo(seq=0, ack=0, flags=forensic.PSEUDOTCP_FLAG_CTL), client_to_device=True),
                packet(pseudo(seq=0, ack=0, flags=forensic.PSEUDOTCP_FLAG_CTL), client_to_device=False),
            ]
        )
        capture = forensic.load_capture(self.write_capture(blob))
        with self.assertRaisesRegex(ValueError, "no PseudoTCP flow"):
            forensic.select_vip_flow(capture)

    def test_analyzer_source_has_no_network_or_actuation_surface(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import socket",
            "import requests",
            "import aiohttp",
            "subprocess",
            "api.comelitgroup.com",
            "button.press",
            "SIGUSR1",
            "open_door",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn('"NETWORK_IO_PERFORMED=false"', text)
        self.assertIn('"DOOR_ACTION_SENT=false"', text)
        self.assertIn('"SELF_ACTIVATION_SENT=false"', text)
        self.assertIn('"MEDIA_SIGNALING_SENT=false"', text)


if __name__ == "__main__":
    unittest.main()
