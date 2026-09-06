import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
SOURCE = ROOT / "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA_DIR / "entrance_device_video_ack_observation_transform.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_device_video_ack_observation_transform",
    TRANSFORM,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P46EntranceDeviceVideoAckObservationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SOURCE.read_text(encoding="utf-8")
        cls.transform_text = TRANSFORM.read_text(encoding="utf-8")
        cls.candidate = module.transform(cls.original)

    def test_inherits_proven_signaling_and_reuses_registered_ctpp(self):
        for marker in (
            "ENTRANCE_SELF_ACTIVATION_ACTION=0x0028",
            "ENTRANCE_SELF_ACTIVATION_ACK=PASS",
            "ENTRANCE_VIDEO_EVENT_ACTION=0x0008",
            "ENTRANCE_VIDEO_EVENT_ACK=PASS",
            "ENTRANCE_DEVICE_VIDEO_EVENT=PASS",
            "ENTRANCE_SIGNALING_SECOND_CTPP_OPEN=false",
            "ENTRANCE_DEVICE_VIDEO_ACK_CTPP_REUSED=true",
        ):
            self.assertIn(marker, self.candidate)

    def test_client_video_sequence_is_saved_and_ack_delta_is_session_derived(self):
        self.assertIn(
            "static guint32 entrance_video_event_sequence = 0;",
            self.candidate,
        )
        self.assertIn(
            "entrance_video_event_sequence = entrance_signal_sequence + 0x00010000u;",
            self.candidate,
        )
        self.assertIn(
            "write_le32(body + 2, entrance_video_event_sequence);",
            self.candidate,
        )
        self.assertIn(
            "#define ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO 0x01010000u",
            self.candidate,
        )
        self.assertIn(
            "entrance_device_video_ack_sequence =\n        entrance_video_event_sequence +\n        ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO;",
            self.candidate,
        )
        self.assertIn(
            "ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO=0x01010000",
            self.candidate,
        )
        self.assertIn("ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_EMITTED=false", self.candidate)

        # Capture/session literals must not be substituted for generated state.
        for forbidden in (
            "0x748cff80",
            "0x758cff80",
            "0x768cff80",
        ):
            self.assertNotIn(forbidden, self.candidate.lower())

    def test_ack_body_uses_capture_derived_reversed_address_roles(self):
        expected = (
            "write_le16(body + 0, 0x1800);",
            "body[6] = 0x00;",
            "body[7] = 0x00;",
            "memset(body + 8, 0xff, 4);",
            "memcpy(body + 12, V4_FULL_ADDRESS, 9);",
            "body[21] = 0x00;",
            "memcpy(body + 22, V4_ENTRANCE, 8);",
            "body[30] = 0x00;",
            "body[31] = 0x00;",
            "ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true",
        )
        for marker in expected:
            self.assertIn(marker, self.candidate)

    def test_exact_device_video_is_consumed_before_ack_is_queued(self):
        matcher = "entrance_signal_body_is_device_video(body, body_len)"
        consume = "p12_consume_post_ack(frame_len);"
        queue = "return entrance_signal_queue_device_video_ack();"

        matcher_index = self.candidate.index(matcher)
        consume_index = self.candidate.index(consume, matcher_index)
        queue_index = self.candidate.index(queue, consume_index)

        self.assertLess(matcher_index, consume_index)
        self.assertLess(consume_index, queue_index)
        self.assertNotIn(
            "p12_consume_post_ack(frame_len);\n                return entrance_signal_begin_media_observation();",
            self.candidate,
        )

    def test_ack_is_one_shot_and_observation_starts_only_after_tx_completion(self):
        for marker in (
            "ENTRANCE_SIGNAL_DEVICE_VIDEO_ACK_TX",
            "P12_TX_ENTRANCE_DEVICE_VIDEO_ACK",
            "static gboolean entrance_device_video_ack_sent = FALSE;",
            "entrance_device_video_ack_sent = TRUE;",
            "ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS",
            "ENTRANCE_MEDIA_OBSERVATION_DEVICE_VIDEO_ACK_SENT=true",
            "ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true",
        ):
            self.assertIn(marker, self.candidate)

        helper_start = self.candidate.index("entrance_signal_queue_device_video_ack(void)")
        helper_end = self.candidate.index("entrance_media_observation_finish_cb", helper_start)
        helper = self.candidate[helper_start:helper_end]
        self.assertIn("entrance_device_video_ack_sent ||", helper)
        self.assertEqual(helper.count("p12_queue_vip_frame("), 1)
        self.assertEqual(helper.count("P12_TX_ENTRANCE_DEVICE_VIDEO_ACK"), 1)

        tx_case = self.candidate.index("case P12_TX_ENTRANCE_DEVICE_VIDEO_ACK:")
        begin_after_case = self.candidate.index(
            "entrance_signal_begin_media_observation()",
            tx_case,
        )
        door_case = self.candidate.index("case P12_TX_V4_DOOR_WRITE:", tx_case)
        self.assertLess(begin_after_case, door_case)

        begin_function = self.candidate.index("entrance_signal_begin_media_observation(void)")
        begin_body_end = self.candidate.index("return TRUE;", begin_function)
        begin_body = self.candidate[begin_function:begin_body_end]
        self.assertIn(
            "entrance_signal_stage != ENTRANCE_SIGNAL_DEVICE_VIDEO_ACK_TX",
            begin_body,
        )
        self.assertIn("!entrance_device_video_ack_sent", begin_body)

    def test_observation_remains_metadata_only_bounded_and_graceful(self):
        for marker in (
            "#define ENTRANCE_MEDIA_OBSERVE_MS 3000",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false",
            "memset(buf, 0, (gsize)n);",
            "pseudo_tcp_socket_close(pseudo_tcp, FALSE);",
            "PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false",
        ):
            self.assertIn(marker, self.candidate)

        self.assertNotIn("pseudo_tcp_socket_close(pseudo_tcp, TRUE);", self.candidate)
        self.assertNotIn("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=true", self.candidate)
        self.assertNotIn("ENTRANCE_RTP_H264_INSPECTION_PERFORMED=true", self.candidate)

    def test_door_surface_remains_unreachable(self):
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)
        self.assertNotIn(
            "g_timeout_add(\n        100,\n        v4_door_tick_cb,\n        NULL\n    );",
            self.candidate,
        )
        self.assertIn("ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false", self.candidate)
        self.assertIn("ENTRANCE_DOOR_ACTION_SENT=false", self.candidate)

    def test_transform_is_offline_only_and_adds_no_live_launcher(self):
        for forbidden in (
            "import socket",
            "import requests",
            "import aiohttp",
            "subprocess",
            "urllib.request",
            "api.comelitgroup.com",
            "os.kill",
        ):
            self.assertNotIn(forbidden, self.transform_text)

        for required in (
            'print("NETWORK_IO_PERFORMED=false")',
            'print("DOOR_ACTION_SENT=false")',
            'print("ENTRANCE_DEVICE_VIDEO_ACK_MAX_SENDS=1")',
        ):
            self.assertIn(required, self.transform_text)

        self.assertNotIn("ct120_launch_", self.transform_text)
        self.assertNotIn("timeout --signal", self.transform_text)


if __name__ == "__main__":
    unittest.main()
