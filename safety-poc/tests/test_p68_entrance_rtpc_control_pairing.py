from contextlib import redirect_stdout
from dataclasses import replace
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MEDIA = Path(__file__).resolve().parents[1] / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))
import entrance_rtpc_control_pairing_pcap_forensic as p68
from entrance_device_video_ack_pcap_forensic import VipFrame
from entrance_rtpc_control_response_contract_pcap_forensic import analyze as p67_analyze


def frame(sender, packet, body):
    return VipFrame(sender, packet, packet, float(packet), 0, bytes(body))


def open_body(target, name=b"RTPC"):
    return (b"\xcd\xab\x01\x00\x07\x00\x00\x00" + name
            + target.to_bytes(2, "little") + b"\0")


def response_body(target):
    return (b"\xcd\xab\x02\x00\x04\x00\x00\x00"
            + target.to_bytes(2, "little") + b"\0\0")


def fixture():
    # Fictional ids and packet bodies. Reproduce only the observed P67
    # structural symptoms: OPEN zeros rejected, response differs at 8 and 9,
    # response target belongs to neither of the two client-created channels.
    return [
        frame("DEVICE_TO_CLIENT", 205, open_body(0x5678)),
        frame("CLIENT_TO_DEVICE", 206, open_body(0x1234)),
        frame("CLIENT_TO_DEVICE", 206, open_body(0x1235)),
        frame("DEVICE_TO_CLIENT", 207, response_body(0x1234)),
        frame("CLIENT_TO_DEVICE", 208, response_body(0x5678)),
        frame("DEVICE_TO_CLIENT", 209, response_body(0x1235)),
    ]


class P68ControlPairingTests(unittest.TestCase):
    def test_reproduces_p67_observed_failure_without_claiming_real_capture(self):
        old = p67_analyze(fixture())
        self.assertFalse(old.open_full_template_ok)
        self.assertFalse(old.client_response_exact_preceding_echo)
        self.assertEqual(old.client_response_diff_positions, (8, 9))
        self.assertEqual(old.client_response_request_id_ordinals, ())

    def test_typed_pairing_accepts_three_independent_open_responses(self):
        result = p68.analyze(fixture())
        self.assertTrue(result.pairing_ok)
        self.assertEqual(result.legacy_open_mismatches, ((2, 4), (2, 4)))
        self.assertEqual(result.typed_open_mismatches, ((), ()))
        self.assertEqual(result.client_pairs[0].open_packet, 205)
        self.assertTrue(result.client_response_diff_only_target)

    def test_nearest_echo_is_not_a_reply_to_device_open(self):
        frames = fixture()
        frames[4] = replace(frames[4], body=frames[3].body)
        result = p68.analyze(frames)
        self.assertFalse(result.pairing_ok)
        self.assertEqual(result.client_pairs[0].matching_open_count, 0)

    def test_missing_or_ambiguous_device_open_fails(self):
        for frames in (fixture()[1:], [replace(fixture()[0], first_packet=204, last_packet=204, timestamp=204.0)] + fixture()):
            with self.subTest(count=len(frames)):
                self.assertFalse(p68.analyze(frames).pairing_ok)

    def test_later_or_same_packet_open_cannot_explain_response(self):
        for packet in (208, 209):
            frames = fixture()
            frames[0] = replace(frames[0], first_packet=packet, last_packet=packet, timestamp=float(packet))
            result = p68.analyze(frames)
            self.assertFalse(result.pairing_ok)
            self.assertEqual(result.client_pairs[0].matching_open_count, 0)

    def test_invalid_schema_fields_fail_closed(self):
        for index, offsets in ((0, (0, 2, 4, 8, 14)), (1, (0, 2, 4, 14)), (3, (0, 2, 4, 10)), (4, (0, 2, 4, 10))):
            for offset in offsets:
                frames = fixture()
                body = bytearray(frames[index].body)
                body[offset] ^= 1
                frames[index] = replace(frames[index], body=bytes(body))
                with self.subTest(index=index, offset=offset):
                    self.assertFalse(p68.analyze(frames).pairing_ok)

    def test_reused_or_zero_or_nonsequential_client_ids_fail(self):
        for targets in ((0x1234, 0x1234), (0, 1), (0x1234, 0x1236)):
            frames = fixture()
            frames[1] = replace(frames[1], body=open_body(targets[0]))
            frames[2] = replace(frames[2], body=open_body(targets[1]))
            frames[3] = replace(frames[3], body=response_body(targets[0]))
            frames[5] = replace(frames[5], body=response_body(targets[1]))
            self.assertFalse(p68.analyze(frames).pairing_ok)

    def test_duplicate_device_response_cannot_ack_two_opens(self):
        frames = fixture()
        frames[5] = replace(frames[5], body=frames[3].body)
        self.assertFalse(p68.analyze(frames).pairing_ok)

    def test_unknown_or_extra_controls_do_not_disappear(self):
        frames = fixture() + [frame("DEVICE_TO_CLIENT", 209, b"private-data")]
        result = p68.analyze(frames)
        self.assertFalse(result.pairing_ok)
        self.assertEqual(len(result.controls), 7)
        self.assertNotIn("private-data", p68.report(result))

    def test_other_channel_is_reported_but_does_not_prove_rtpc(self):
        frames = fixture()
        frames[0] = replace(frames[0], body=open_body(0x5678, b"ECHO"))
        result = p68.analyze(frames)
        self.assertEqual(result.client_pairs[0].open_channel, "ECHO")
        self.assertFalse(result.pairing_ok)

    def test_all_short_control_lengths_are_bounded(self):
        for length in range(15):
            frames = fixture()
            frames[0] = replace(frames[0], body=b"\xff" * length)
            self.assertFalse(p68.analyze(frames).pairing_ok)

    def test_report_omits_ids_payload_and_does_not_authorize_live(self):
        text = p68.report(p68.analyze(fixture()))
        for value in ("1234", "1235", "5678", "4660", "4661", "22136", "3412", "7856"):
            self.assertNotIn(value, text)
        self.assertIn("RTPC_CONTROL_PAIRING_CONTRACT=PASS", text)
        self.assertIn("LIVE_RUN_AUTHORIZED_BY_ANALYZER=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)

    def test_cli_digest_failure_does_not_parse_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.pcap"
            path.write_bytes(b"not-the-frozen-capture")
            with patch.object(p68, "load_capture") as loader, redirect_stdout(io.StringIO()) as output:
                rc = p68.main(["--pcap", str(path)])
            self.assertEqual(rc, 2)
            loader.assert_not_called()
            self.assertIn("PCAP_SHA256_GATE=FAIL", output.getvalue())

    def test_cli_not_proven_is_nonzero_and_exceptions_are_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.pcap"
            path.write_bytes(b"synthetic")
            digest = p68.hashlib.sha256(b"synthetic").hexdigest()
            with patch.object(p68, "EXPECTED_PCAP_SHA256", digest), patch.object(p68, "load_capture"), patch.object(p68, "select_vip_flow"), patch.object(p68, "collect_extended_vip_frames", return_value=[]), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(p68.main(["--pcap", str(path)]), 4)
            self.assertIn("RTPC_CONTROL_PAIRING_CONTRACT=NOT_PROVEN", output.getvalue())
            with patch.object(p68, "EXPECTED_PCAP_SHA256", digest), patch.object(p68, "load_capture", side_effect=ValueError("secret-payload")), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(p68.main(["--pcap", str(path)]), 3)
            self.assertNotIn("secret-payload", output.getvalue())


if __name__ == "__main__":
    unittest.main()
