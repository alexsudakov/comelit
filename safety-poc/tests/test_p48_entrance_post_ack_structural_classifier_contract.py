import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
SOURCE = ROOT / "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA_DIR / "entrance_post_ack_structural_classifier_transform.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_post_ack_structural_classifier_transform",
    TRANSFORM,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P48EntrancePostAckStructuralClassifierContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SOURCE.read_text(encoding="utf-8")
        cls.transform_text = TRANSFORM.read_text(encoding="utf-8")
        cls.candidate = module.transform(cls.original)

    def test_inherits_reviewed_one_shot_ack_boundary(self):
        for marker in (
            "ENTRANCE_SELF_ACTIVATION_ACTION=0x0028",
            "ENTRANCE_VIDEO_EVENT_ACTION=0x0008",
            "ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS",
            "ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO=0x01010000",
            "ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true",
            "ENTRANCE_DEVICE_VIDEO_ACK_CTPP_REUSED=true",
            "ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true",
            "ENTRANCE_SIGNALING_SECOND_CTPP_OPEN=false",
        ):
            self.assertIn(marker, self.candidate)

        self.assertNotIn("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false", self.candidate)

    def test_classifier_is_bounded_and_structural_only(self):
        for marker in (
            "#define ENTRANCE_POST_ACK_CLASSIFIER_MAX 512",
            "read_le16(entrance_post_ack_classifier_buf + 2)",
            "read_le32(entrance_post_ack_classifier_buf + 4)",
            'channel = "CTPP";',
            'channel = "CSPB";',
            'channel = "CONTROL";',
            "PREFIX=0x%04x",
            "ACTION=0x%04x",
            "FLAGS=0x%04x",
            "ENTRANCE_POST_ACK_STRUCT_FRAME=%u",
        ):
            self.assertIn(marker, self.candidate)

        self.assertIn(
            "if (body_len == 0 || frame_len > ENTRANCE_POST_ACK_CLASSIFIER_MAX)",
            self.candidate,
        )
        self.assertIn("ENTRANCE_POST_ACK_CLASSIFIER_OVERFLOW=true", self.candidate)
        self.assertIn("ENTRANCE_POST_ACK_CLASSIFIER_LENGTH_INVALID=%u", self.candidate)

    def test_coalesced_bytes_are_classified_before_erasure(self):
        start = self.candidate.index("if (post_ack_capture_len > 0)")
        end = self.candidate.index("post_ack_capture_len = 0;", start) + len(
            "post_ack_capture_len = 0;"
        )
        block = self.candidate[start:end]

        feed = block.index(
            "entrance_post_ack_classifier_feed(post_ack_capture, post_ack_capture_len)"
        )
        erase = block.index("memset(post_ack_capture, 0, post_ack_capture_len)")
        self.assertLess(feed, erase)
        self.assertIn("ENTRANCE_POST_ACK_CLASSIFIER_COALESCED_FEED=FAIL", self.candidate)

    def test_readable_bytes_are_classified_before_erasure_and_short_circuit(self):
        marker = "if (entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA)"
        start = self.candidate.index(marker)
        end = self.candidate.index("continue;", start) + len("continue;")
        block = self.candidate[start:end]

        feed = block.index(
            "entrance_post_ack_classifier_feed((const guint8 *)buf, (guint)n)"
        )
        erase = block.index("memset(buf, 0, (gsize)n)", feed)
        self.assertLess(feed, erase)
        self.assertIn("ENTRANCE_MEDIA_OBSERVATION_RX_EVENT=%d", block)

    def test_classifier_reassembles_across_receive_chunks_and_zeroes_consumed_bytes(self):
        for marker in (
            "memcpy(\n        entrance_post_ack_classifier_buf + entrance_post_ack_classifier_len",
            "if (entrance_post_ack_classifier_len < frame_len)",
            "memmove(\n                entrance_post_ack_classifier_buf",
            "memset(\n            entrance_post_ack_classifier_buf + remaining",
        ):
            self.assertIn(marker, self.candidate)

    def test_summary_reports_only_structural_metadata(self):
        for marker in (
            "ENTRANCE_POST_ACK_STRUCT_FRAMES=%u",
            "ENTRANCE_POST_ACK_STRUCT_CTPP_FRAMES=%u",
            "ENTRANCE_POST_ACK_STRUCT_OTHER_FRAMES=%u",
            "ENTRANCE_POST_ACK_STRUCT_MALFORMED=%u",
            "ENTRANCE_POST_ACK_STRUCT_TAIL_BYTES=%u",
            "ENTRANCE_POST_ACK_STRUCT_RAW_PAYLOAD_EMITTED=false",
            "ENTRANCE_POST_ACK_STRUCT_HEX_EMITTED=false",
            "ENTRANCE_POST_ACK_STRUCT_BASE64_EMITTED=false",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false",
        ):
            self.assertIn(marker, self.candidate)

        for forbidden in (
            "ENTRANCE_POST_ACK_STRUCT_RAW_PAYLOAD_EMITTED=true",
            "ENTRANCE_POST_ACK_STRUCT_HEX_EMITTED=true",
            "ENTRANCE_POST_ACK_STRUCT_BASE64_EMITTED=true",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=true",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=true",
            "PAYLOAD_HEX",
            "PAYLOAD_BASE64",
            "printf(\"%02x",
        ):
            self.assertNotIn(forbidden, self.candidate)

    def test_observation_remains_three_seconds_and_graceful(self):
        self.assertIn("#define ENTRANCE_MEDIA_OBSERVE_MS 3000", self.candidate)
        self.assertIn("pseudo_tcp_socket_close(pseudo_tcp, FALSE);", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false", self.candidate)
        self.assertNotIn("pseudo_tcp_socket_close(pseudo_tcp, TRUE);", self.candidate)

    def test_door_surface_remains_unreachable(self):
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)
        self.assertNotIn(
            "g_timeout_add(\n        100,\n        v4_door_tick_cb,\n        NULL\n    );",
            self.candidate,
        )
        self.assertIn("ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false", self.candidate)
        self.assertIn("ENTRANCE_DOOR_ACTION_SENT=false", self.candidate)

    def test_transform_is_offline_only_and_adds_no_launcher(self):
        for forbidden in (
            "import socket",
            "import requests",
            "import aiohttp",
            "subprocess",
            "urllib.request",
            "api.comelitgroup.com",
            "os.kill",
            "timeout --signal",
            "ct120_launch_",
        ):
            self.assertNotIn(forbidden, self.transform_text)

        for required in (
            'print("NETWORK_IO_PERFORMED=false")',
            'print("DOOR_ACTION_SENT=false")',
            'print("ENTRANCE_DEVICE_VIDEO_ACK_MAX_SENDS=1")',
            'print("ENTRANCE_POST_ACK_STRUCTURAL_CLASSIFIER_MAX=512")',
        ):
            self.assertIn(required, self.transform_text)


if __name__ == "__main__":
    unittest.main()
