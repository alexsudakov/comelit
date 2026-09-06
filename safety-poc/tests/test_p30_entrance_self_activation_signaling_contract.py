import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
SOURCE = ROOT / "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA_DIR / "entrance_self_activation_signaling_transform.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location("entrance_self_activation_signaling_transform", TRANSFORM)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P30EntranceSelfActivationSignalingContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SOURCE.read_text(encoding="utf-8")
        cls.candidate = module.transform(cls.original)

    def test_transform_is_based_on_v157_and_adds_prestart_replay(self):
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true", self.candidate)
        self.assertIn("PSEUDOTCP_RX_BUFFERED=%u LEN=%u", self.candidate)
        self.assertIn("PSEUDOTCP_PRESTART_REPLAY_COUNT=%u", self.candidate)
        self.assertIn("PSEUDOTCP_STATE_AFTER_PRESTART_REPLAY=%u", self.candidate)

    def test_door_trigger_surface_is_unreachable(self):
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)
        self.assertNotIn(
            "g_timeout_add(\n        100,\n        v4_door_tick_cb,\n        NULL\n    );",
            self.candidate,
        )
        self.assertIn("ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false", self.candidate)
        self.assertIn("ENTRANCE_SIGNALING_DOOR_TIMER_INSTALLED=false", self.candidate)
        self.assertIn("ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false", self.candidate)

    def test_self_activation_is_exactly_one_guarded_capture_shape(self):
        self.assertEqual(self.candidate.count("P12_TX_ENTRANCE_SELF_ACTIVATION"), 3)
        for marker in (
            "ENTRANCE_SELF_ACTIVATION_BODY_LEN=72",
            "ENTRANCE_SELF_ACTIVATION_PREFIX=0x18C0",
            "ENTRANCE_SELF_ACTIVATION_ACTION=0x0028",
            "ENTRANCE_SELF_ACTIVATION_FLAGS=0x0001",
            "ENTRANCE_SELF_ACTIVATION_CTPP_REUSED=true",
            "entrance_self_activation_sent ||",
            "v4_ctpp_channel_id == 0",
        ):
            self.assertIn(marker, self.candidate)

        # Session-state timestamp/sequence from the PCAP is intentionally not replayed.
        self.assertNotIn("0x71FC7B1F", self.candidate)

    def test_client_video_event_is_exactly_one_guarded_capture_shape(self):
        self.assertEqual(self.candidate.count("P12_TX_ENTRANCE_VIDEO_EVENT"), 3)
        for marker in (
            "ENTRANCE_VIDEO_EVENT_BODY_LEN=40",
            "ENTRANCE_VIDEO_EVENT_PREFIX=0x1840",
            "ENTRANCE_VIDEO_EVENT_ACTION=0x0008",
            "ENTRANCE_VIDEO_EVENT_FLAGS=0x0003",
            "entrance_video_event_sent ||",
            "entrance_signal_sequence + 0x00010000u",
        ):
            self.assertIn(marker, self.candidate)

        self.assertNotIn("0x71FD7B1F", self.candidate)

    def test_signaling_order_is_ack_gated(self):
        self.assertIn("ENTRANCE_SIGNAL_WAIT_SELF_ACK", self.candidate)
        self.assertIn("ENTRANCE_SELF_ACTIVATION_ACK=PASS", self.candidate)
        self.assertIn("ENTRANCE_SIGNAL_WAIT_VIDEO_ACK", self.candidate)
        self.assertIn("ENTRANCE_VIDEO_EVENT_ACK=PASS", self.candidate)
        self.assertIn("ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO", self.candidate)
        self.assertIn("ENTRANCE_DEVICE_VIDEO_EVENT=PASS", self.candidate)
        self.assertIn("ENTRANCE_SIGNALING_PROBE_RESULT=PASS", self.candidate)

        self.assertLess(
            self.candidate.index("ENTRANCE_SELF_ACTIVATION_ACK=PASS"),
            self.candidate.index("ENTRANCE_VIDEO_EVENT_ACK=PASS"),
        )

    def test_same_registered_ctpp_is_reused_without_second_open(self):
        self.assertIn("ENTRANCE_SIGNALING_CTPP_REUSE_REQUIRED=true", self.candidate)
        self.assertIn("ENTRANCE_SIGNALING_SECOND_CTPP_OPEN=false", self.candidate)
        self.assertIn(
            "p12_queue_vip_frame(\n        v4_ctpp_channel_id,\n        body,",
            self.candidate,
        )
        # The transform must not add another invocation of the CTPP OPEN helper.
        self.assertEqual(
            self.candidate.count("!v4_queue_open_ctpp()"),
            self.original.count("!v4_queue_open_ctpp()"),
        )

    def test_probe_stops_before_final_device_video_ack_or_media_capture(self):
        for marker in (
            "ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false",
        ):
            self.assertIn(marker, self.candidate)

        self.assertNotIn("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true", self.candidate)
        self.assertNotIn("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=true", self.candidate)

    def test_success_uses_graceful_not_forced_pseudotcp_close(self):
        self.assertIn("pseudo_tcp_socket_close(pseudo_tcp, FALSE);", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false", self.candidate)
        self.assertNotIn("pseudo_tcp_socket_close(pseudo_tcp, TRUE);", self.candidate)

    def test_hard_runtime_is_bounded_and_production_camera_is_not_exposed(self):
        self.assertNotIn("        3300,", self.candidate)
        self.assertIn("        45,", self.candidate)
        self.assertEqual(module.transform(self.original).count("ENTRANCE_SIGNALING_TIMEOUT=true"), 1)

        for forbidden in (
            "switch.comelit_entrance_camera",
            "camera.comelit_entrance",
            "binary_sensor.comelit_entrance_camera_active",
            "sensor.comelit_entrance_camera_session_remaining",
        ):
            self.assertNotIn(forbidden, self.candidate)

    def test_transform_module_itself_has_no_network_or_actuation(self):
        text = TRANSFORM.read_text(encoding="utf-8")
        for forbidden in (
            "import socket",
            "import requests",
            "import aiohttp",
            "subprocess",
            "api.comelitgroup.com",
            "os.kill",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn('print("NETWORK_IO_PERFORMED=false")', text)
        self.assertIn('print("DOOR_ACTION_SENT=false")', text)


if __name__ == "__main__":
    unittest.main()
