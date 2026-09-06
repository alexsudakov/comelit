import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TRANSFORM_PATH = ROOT / "safety-poc/research/media/v1/media_vip_bootstrap_probe_transform.py"
SOURCE_PATH = ROOT / "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"

spec = importlib.util.spec_from_file_location("media_vip_bootstrap_probe_transform", TRANSFORM_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P30MediaVipBootstrapProbeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE_PATH.read_text(encoding="utf-8")
        cls.candidate = module.transform(cls.source)

    def test_terminal_success_is_listener_ready(self):
        self.assertIn('V4_RING_LISTENER_READY=true', self.candidate)
        self.assertIn('MEDIA_VIP_BOOTSTRAP_RESULT=PASS', self.candidate)
        self.assertIn('MEDIA_VIP_BOOTSTRAP_TERMINAL=V4_RING_LISTENER_READY', TRANSFORM_PATH.read_text(encoding="utf-8"))
        self.assertIn('g_main_loop_quit(loop);', self.candidate)

    def test_full_vip_bootstrap_stages_remain(self):
        for marker in (
            'VIP_ECHO_ACK=PASS',
            'VIP_UAUT_OPEN_SENT=PASS',
            'P2_VIP_UAUT_AUTH=PASS',
            'P2_VIP_UCFG_OPEN=PASS',
            'V4_CTPP_OPEN=PASS',
            'V4_CSPB_OPEN=PASS',
            'V4_CTPP_REGISTRATION=PASS',
        ):
            self.assertIn(marker, self.candidate)

    def test_early_pseudotcp_replay_is_enabled(self):
        for marker in (
            'PSEUDOTCP_RX_BUFFERED=%u LEN=%u',
            'PSEUDOTCP_PRESTART_REPLAY_COUNT=%u',
            'PSEUDOTCP_STATE_AFTER_PRESTART_REPLAY=%u',
        ):
            self.assertIn(marker, self.candidate)

    def test_door_runtime_entrypoints_are_unreachable(self):
        self.assertNotIn('signal(SIGUSR1, v4_door_signal_handler);', self.candidate)
        self.assertNotIn(
            'g_timeout_add(\n        100,\n        v4_door_tick_cb,\n        NULL\n    );',
            self.candidate,
        )
        self.assertIn('MEDIA_VIP_BOOTSTRAP_DOOR_SIGNAL_INSTALLED=false', self.candidate)
        self.assertIn('V4_DOOR_ACTION_SURFACE_PRESENT=false', self.candidate)
        self.assertIn('MEDIA_VIP_BOOTSTRAP_DOOR_ACTION_SENT=false', self.candidate)

    def test_no_self_activation_or_video_event_is_added(self):
        self.assertNotIn('SELF_ACTIVATION_SENT=true', self.candidate)
        self.assertNotIn('VIDEO_EVENT_SENT=true', self.candidate)
        self.assertIn('MEDIA_VIP_BOOTSTRAP_SELF_ACTIVATION_SENT=false', self.candidate)
        self.assertIn('MEDIA_VIP_BOOTSTRAP_VIDEO_EVENT_SENT=false', self.candidate)

    def test_timeout_is_bounded(self):
        self.assertIn('media_vip_bootstrap_timeout_cb', self.candidate)
        self.assertIn('        90,\n        media_vip_bootstrap_timeout_cb,', self.candidate)
        self.assertNotIn('        3300,\n        absolute_timeout_cb,', self.candidate)

    def test_transform_itself_has_no_network_surface(self):
        text = TRANSFORM_PATH.read_text(encoding="utf-8")
        for forbidden in (
            'import socket',
            'import requests',
            'import aiohttp',
            'subprocess',
            'api.comelitgroup.com',
            'button.press',
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn('NETWORK_IO_PERFORMED=false', text)
        self.assertIn('DOOR_ACTION_SENT=false', text)
        self.assertIn('SELF_ACTIVATION_SENT=false', text)
        self.assertIn('MEDIA_SIGNALING_SENT=false', text)


if __name__ == "__main__":
    unittest.main()
