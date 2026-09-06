import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
SOURCE = ROOT / "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA_DIR / "entrance_media_structural_classifier_transform.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_media_structural_classifier_transform",
    TRANSFORM,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P39EntranceMediaStructuralClassifierContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SOURCE.read_text(encoding="utf-8")
        cls.transform_text = TRANSFORM.read_text(encoding="utf-8")
        cls.candidate = module.transform(cls.original)

    def test_inherits_proven_signaling_and_no_final_device_ack(self):
        for marker in (
            "ENTRANCE_SELF_ACTIVATION_ACTION=0x0028",
            "ENTRANCE_SELF_ACTIVATION_ACK=PASS",
            "ENTRANCE_VIDEO_EVENT_ACTION=0x0008",
            "ENTRANCE_VIDEO_EVENT_ACK=PASS",
            "ENTRANCE_DEVICE_VIDEO_EVENT=PASS",
            "ENTRANCE_MEDIA_OBSERVATION_DEVICE_VIDEO_ACK_SENT=false",
            "ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false",
        ):
            self.assertIn(marker, self.candidate)
        self.assertNotIn("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true", self.candidate)

    def test_classifier_is_bounded_and_structural_only(self):
        for marker in (
            "#define ENTRANCE_MEDIA_CLASSIFIER_MAX 512",
            "read_le16(entrance_media_classifier_buf + 2)",
            "read_le32(entrance_media_classifier_buf + 4)",
            'channel = "CTPP";',
            'channel = "CSPB";',
            'channel = "CONTROL";',
            "PREFIX=0x%04x",
            "ACTION=0x%04x",
            "FLAGS=0x%04x",
        ):
            self.assertIn(marker, self.candidate)

    def test_classifier_reassembles_across_receive_chunks_then_zeroes_consumed_bytes(self):
        for marker in (
            "memcpy(\n        entrance_media_classifier_buf + entrance_media_classifier_len",
            "if (entrance_media_classifier_len < frame_len)",
            "memmove(\n                entrance_media_classifier_buf",
            "memset(\n            entrance_media_classifier_buf + remaining",
        ):
            self.assertIn(marker, self.candidate)

    def test_no_raw_payload_output_or_rtp_h264_inspection(self):
        for marker in (
            "ENTRANCE_MEDIA_STRUCT_RAW_PAYLOAD_EMITTED=false",
            "ENTRANCE_MEDIA_STRUCT_HEX_EMITTED=false",
            "ENTRANCE_MEDIA_STRUCT_BASE64_EMITTED=false",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false",
        ):
            self.assertIn(marker, self.candidate)

        for forbidden in (
            "ENTRANCE_MEDIA_STRUCT_RAW_PAYLOAD_EMITTED=true",
            "ENTRANCE_MEDIA_STRUCT_HEX_EMITTED=true",
            "ENTRANCE_MEDIA_STRUCT_BASE64_EMITTED=true",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=true",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=true",
            "PAYLOAD_HEX",
            "PAYLOAD_BASE64",
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

    def test_transform_is_offline_only(self):
        for forbidden in (
            "import socket",
            "import requests",
            "import aiohttp",
            "subprocess",
            "api.comelitgroup.com",
            "os.kill",
        ):
            self.assertNotIn(forbidden, self.transform_text)

        for required in (
            'print("NETWORK_IO_PERFORMED=false")',
            'print("DOOR_ACTION_SENT=false")',
            'print("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false")',
            'print("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false")',
        ):
            self.assertIn(required, self.transform_text)


if __name__ == "__main__":
    unittest.main()
