import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
SOURCE = ROOT / "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA_DIR / "entrance_media_observation_transform.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_media_observation_transform",
    TRANSFORM,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P36EntranceMediaObservationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SOURCE.read_text(encoding="utf-8")
        cls.transform_text = TRANSFORM.read_text(encoding="utf-8")
        cls.candidate = module.transform(cls.original)

    def test_composes_reviewed_p30_signaling_boundary(self):
        self.assertEqual(self.candidate.count("P12_TX_ENTRANCE_SELF_ACTIVATION"), 3)
        self.assertEqual(self.candidate.count("P12_TX_ENTRANCE_VIDEO_EVENT"), 3)
        for marker in (
            "ENTRANCE_SELF_ACTIVATION_ACTION=0x0028",
            "ENTRANCE_SELF_ACTIVATION_ACK=PASS",
            "ENTRANCE_VIDEO_EVENT_ACTION=0x0008",
            "ENTRANCE_VIDEO_EVENT_ACK=PASS",
            "ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO",
            "ENTRANCE_DEVICE_VIDEO_EVENT=PASS",
        ):
            self.assertIn(marker, self.candidate)

        self.assertLess(
            self.candidate.index("ENTRANCE_SELF_ACTIVATION_ACK=PASS"),
            self.candidate.index("ENTRANCE_VIDEO_EVENT_ACK=PASS"),
        )

    def test_same_registered_ctpp_is_reused_without_second_open(self):
        self.assertIn("ENTRANCE_SIGNALING_CTPP_REUSE_REQUIRED=true", self.candidate)
        self.assertIn("ENTRANCE_SIGNALING_SECOND_CTPP_OPEN=false", self.candidate)
        self.assertEqual(
            self.candidate.count("!v4_queue_open_ctpp()"),
            self.original.count("!v4_queue_open_ctpp()"),
        )

    def test_device_video_transitions_to_bounded_observation_without_ack(self):
        transition = (
            "p12_consume_post_ack(frame_len);\n"
            "                return entrance_signal_begin_media_observation();"
        )
        self.assertIn(transition, self.candidate)
        self.assertIn("ENTRANCE_SIGNAL_OBSERVE_MEDIA", self.candidate)
        self.assertIn("#define ENTRANCE_MEDIA_OBSERVE_MS 3000", self.candidate)
        self.assertIn("ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=%u", self.candidate)
        self.assertIn(
            "ENTRANCE_MEDIA_OBSERVATION_DEVICE_VIDEO_ACK_SENT=false",
            self.candidate,
        )
        self.assertNotIn("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true", self.candidate)

    def test_observation_readable_path_counts_metadata_before_generic_capture(self):
        observation = "if (entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA) {"
        generic_capture = "pseudotcp_app_bytes_in +="
        self.assertIn(observation, self.candidate)
        self.assertIn(generic_capture, self.candidate)
        self.assertLess(self.candidate.index(observation), self.candidate.index(generic_capture))

        observation_block_end = self.candidate.index(generic_capture)
        observation_block = self.candidate[
            self.candidate.index(observation):observation_block_end
        ]
        for required in (
            "entrance_media_observation_events++;",
            "entrance_media_observation_bytes += (guint64)n;",
            "entrance_media_observation_max_chunk = (guint)n;",
            "ENTRANCE_MEDIA_OBSERVATION_RX_EVENT=%d",
            "memset(buf, 0, (gsize)n);",
            "continue;",
        ):
            self.assertIn(required, observation_block)

        self.assertNotIn("memcpy(", observation_block)

    def test_coalesced_post_device_bytes_are_counted_then_erased(self):
        start = self.candidate.index("if (post_ack_capture_len > 0) {")
        end = self.candidate.index(
            'printf("ENTRANCE_DEVICE_VIDEO_EVENT=PASS',
            start,
        )
        block = self.candidate[start:end]
        for required in (
            "entrance_media_observation_events++;",
            "entrance_media_observation_bytes += (guint64)post_ack_capture_len;",
            "entrance_media_observation_max_chunk = post_ack_capture_len;",
            "memset(post_ack_capture, 0, post_ack_capture_len);",
            "post_ack_capture_len = 0;",
        ):
            self.assertIn(required, block)

    def test_observation_emits_only_metadata_and_never_media_payload_content(self):
        for marker in (
            "ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS",
            "ENTRANCE_MEDIA_OBSERVATION_EVENTS=%u",
            "ENTRANCE_MEDIA_OBSERVATION_BYTES=%",
            "ENTRANCE_MEDIA_OBSERVATION_MAX_CHUNK=%u",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false",
        ):
            self.assertIn(marker, self.candidate)

        for forbidden in (
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_HEX",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_BASE64",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=true",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=true",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=true",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=true",
        ):
            self.assertNotIn(forbidden, self.candidate)

    def test_door_surface_remains_unreachable(self):
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)
        self.assertNotIn(
            "g_timeout_add(\n        100,\n        v4_door_tick_cb,\n        NULL\n    );",
            self.candidate,
        )
        self.assertIn("ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false", self.candidate)
        self.assertIn("ENTRANCE_DOOR_ACTION_SENT=false", self.candidate)

    def test_runtime_and_graceful_close_remain_bounded(self):
        self.assertNotIn("        3300,", self.candidate)
        self.assertIn("        45,", self.candidate)
        self.assertIn("ENTRANCE_MEDIA_OBSERVE_MS 3000", self.candidate)
        self.assertIn("pseudo_tcp_socket_close(pseudo_tcp, FALSE);", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false", self.candidate)
        self.assertNotIn("pseudo_tcp_socket_close(pseudo_tcp, TRUE);", self.candidate)

    def test_transform_module_is_offline_only(self):
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
            'print("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false")',
            'print("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false")',
        ):
            self.assertIn(required, self.transform_text)


if __name__ == "__main__":
    unittest.main()
