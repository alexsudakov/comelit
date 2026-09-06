import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
SOURCE = ROOT / "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA_DIR / "entrance_media_timing_observation_transform.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_media_timing_observation_transform",
    TRANSFORM,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P39EntranceMediaTimingObservationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SOURCE.read_text(encoding="utf-8")
        cls.transform_text = TRANSFORM.read_text(encoding="utf-8")
        cls.candidate = module.transform(cls.original)

    def test_inherits_reviewed_metadata_only_observation_boundary(self):
        for marker in (
            "ENTRANCE_DEVICE_VIDEO_EVENT=PASS",
            "ENTRANCE_MEDIA_OBSERVATION_STARTED=true",
            "ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS",
            "ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=%u",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false",
            "ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false",
        ):
            self.assertIn(marker, self.candidate)

        self.assertIn("#define ENTRANCE_MEDIA_OBSERVE_MS 3000", self.candidate)
        self.assertNotIn("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true", self.candidate)

    def test_each_fragment_emits_only_order_length_and_monotonic_timing(self):
        self.assertIn("static guint entrance_media_observation_event_index = 0;", self.candidate)
        self.assertIn("static gint64 entrance_media_observation_start_us = 0;", self.candidate)
        self.assertIn("static gint64 entrance_media_observation_last_event_us = 0;", self.candidate)
        self.assertIn("g_get_monotonic_time()", self.candidate)
        self.assertIn("ENTRANCE_MEDIA_TIMING_CLOCK=MONOTONIC_US", self.candidate)
        self.assertIn(
            "ENTRANCE_MEDIA_TIMING_EVENT_INDEX=%u ORIGIN=%s LEN=%u ",
            self.candidate,
        )
        self.assertIn("SINCE_START_US=%", self.candidate)
        self.assertIn("DELTA_US=%", self.candidate)

    def test_first_event_delta_is_zero_by_construction(self):
        helper_start = self.candidate.index("static void\nentrance_media_timing_record_event")
        helper_end = self.candidate.index(
            "static gboolean\nentrance_media_observation_finish_cb",
            helper_start,
        )
        helper = self.candidate[helper_start:helper_end]

        self.assertIn("guint64 delta_us = 0;", helper)
        self.assertIn("if (entrance_media_observation_last_event_us > 0", helper)
        self.assertIn("entrance_media_observation_last_event_us = now_us;", helper)
        self.assertNotIn("memcpy(", helper)
        self.assertNotIn("post_ack_capture", helper)
        self.assertNotIn("buf", helper)

    def test_coalesced_bytes_are_timing_recorded_then_erased(self):
        start = self.candidate.index("if (post_ack_capture_len > 0) {")
        end = self.candidate.index("post_ack_capture_len = 0;", start) + len(
            "post_ack_capture_len = 0;"
        )
        block = self.candidate[start:end]

        self.assertIn("entrance_media_timing_record_event(", block)
        self.assertIn("post_ack_capture_len,", block)
        self.assertIn('"COALESCED"', block)
        self.assertIn("memset(post_ack_capture, 0, post_ack_capture_len);", block)
        self.assertLess(
            block.index("entrance_media_timing_record_event("),
            block.index("memset(post_ack_capture, 0, post_ack_capture_len);"),
        )

    def test_later_readable_fragments_are_timing_recorded_then_erased(self):
        start = self.candidate.index(
            "if (entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA) {"
        )
        end = self.candidate.index("continue;", start) + len("continue;")
        block = self.candidate[start:end]

        self.assertIn("entrance_media_timing_record_event(", block)
        self.assertIn("(guint)n,", block)
        self.assertIn('"READABLE"', block)
        self.assertIn("memset(buf, 0, (gsize)n);", block)
        self.assertLess(
            block.index("entrance_media_timing_record_event("),
            block.index("memset(buf, 0, (gsize)n);"),
        )
        self.assertNotIn("memcpy(", block)

    def test_timing_stage_does_not_add_payload_content_output(self):
        for forbidden in (
            "ENTRANCE_MEDIA_TIMING_PAYLOAD_HEX",
            "ENTRANCE_MEDIA_TIMING_PAYLOAD_BASE64",
            "ENTRANCE_MEDIA_TIMING_PAYLOAD_TEXT",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=true",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=true",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=true",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=true",
        ):
            self.assertNotIn(forbidden, self.candidate)

        self.assertIn('"COALESCED"', self.candidate)
        self.assertIn('"READABLE"', self.candidate)

    def test_timing_finish_reports_event_count_without_changing_close_policy(self):
        self.assertIn("ENTRANCE_MEDIA_TIMING_OBSERVATION_RESULT=PASS", self.candidate)
        self.assertIn("ENTRANCE_MEDIA_TIMING_EVENT_COUNT=%u", self.candidate)
        self.assertIn("pseudo_tcp_socket_close(pseudo_tcp, FALSE);", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false", self.candidate)
        self.assertNotIn("pseudo_tcp_socket_close(pseudo_tcp, TRUE);", self.candidate)

    def test_door_and_signaling_safety_boundary_is_unchanged(self):
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)
        self.assertIn("ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false", self.candidate)
        self.assertIn("ENTRANCE_DOOR_ACTION_SENT=false", self.candidate)
        self.assertIn("ENTRANCE_SELF_ACTIVATION_ACTION=0x0028", self.candidate)
        self.assertIn("ENTRANCE_VIDEO_EVENT_ACTION=0x0008", self.candidate)
        self.assertIn("ENTRANCE_SIGNALING_SECOND_CTPP_OPEN=false", self.candidate)

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
            'print("ENTRANCE_MEDIA_TIMING_OBSERVATION_TRANSFORM=PASS")',
            'print("ENTRANCE_MEDIA_TIMING_CLOCK=MONOTONIC_US")',
            'print("ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=3000")',
            'print("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false")',
            'print("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false")',
            'print("ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false")',
            'print("DOOR_ACTION_SENT=false")',
            'print("NETWORK_IO_PERFORMED=false")',
        ):
            self.assertIn(required, self.transform_text)


if __name__ == "__main__":
    unittest.main()
