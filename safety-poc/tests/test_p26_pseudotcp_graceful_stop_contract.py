import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "safety-poc/research/door/v1_5_3/comelit-v4-persistent-ctpp-door.c"
TRANSFORM = ROOT / "safety-poc/research/media/v1/pseudotcp_graceful_stop_transform.py"

spec = importlib.util.spec_from_file_location("pseudotcp_graceful_stop_transform", TRANSFORM)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P26PseudoTcpGracefulStopContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = SOURCE.read_text(encoding="utf-8")
        cls.candidate = module.transform(cls.original)

    def test_current_stop_path_has_no_explicit_pseudotcp_close(self):
        start = self.original.index("static gboolean\nstop_check_cb")
        end = self.original.index("\n}\n", start) + 3
        stop_block = self.original[start:end]
        self.assertIn("g_main_loop_quit(loop)", stop_block)
        self.assertNotIn("pseudo_tcp_socket_close", stop_block)
        self.assertNotIn("pseudo_tcp_socket_shutdown", stop_block)

    def test_candidate_requests_graceful_close_exactly_once(self):
        self.assertEqual(
            self.candidate.count("pseudo_tcp_socket_close(pseudo_tcp, FALSE);"),
            1,
        )
        self.assertNotIn("pseudo_tcp_socket_close(pseudo_tcp, TRUE);", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false", self.candidate)

    def test_candidate_drains_receive_buffer_before_close(self):
        drain = self.candidate.index("pseudotcp_drain_before_graceful_close")
        close = self.candidate.index("pseudo_tcp_socket_close(pseudo_tcp, FALSE);")
        self.assertLess(drain, close)
        self.assertIn("pseudo_tcp_socket_recv", self.candidate[drain:close])
        self.assertIn("EWOULDBLOCK", self.candidate[drain:close])

    def test_candidate_keeps_loop_alive_for_bounded_close_handshake(self):
        self.assertIn("PSEUDOTCP_GRACEFUL_STOP_TIMEOUT_MS 5000", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_STOP_POLL_MS     100", self.candidate)
        self.assertIn("pseudo_tcp_socket_get_next_clock", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=true", self.candidate)
        self.assertIn("g_timeout_add", self.candidate)

    def test_stop_is_idempotent_during_grace_window(self):
        self.assertIn("static gboolean pseudotcp_graceful_stop_started = FALSE;", self.candidate)
        self.assertIn("if (pseudotcp_graceful_stop_started)", self.candidate)
        self.assertIn("pseudotcp_graceful_stop_started = TRUE;", self.candidate)

    def test_unopened_socket_still_stops_immediately(self):
        self.assertIn("if (!pseudo_tcp || !pseudotcp_open)", self.candidate)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_SKIPPED_NOT_OPEN=true", self.candidate)

    def test_no_door_or_media_surface_is_added(self):
        added = self.candidate.replace(self.original, "")
        # Compare counts rather than banning existing Door code inherited from source.
        self.assertEqual(
            self.candidate.count("v4_door_signal_handler"),
            self.original.count("v4_door_signal_handler"),
        )
        self.assertEqual(
            self.candidate.count("V4_DOOR_RESULT"),
            self.original.count("V4_DOOR_RESULT"),
        )
        for forbidden in (
            "self_activation",
            "MEDIA_SIGNALING_SENT=true",
            "DOOR_ACTION_SENT=true",
        ):
            self.assertNotIn(forbidden, added)

    def test_transform_module_is_offline(self):
        text = TRANSFORM.read_text(encoding="utf-8")
        for forbidden in (
            "import socket",
            "import requests",
            "import aiohttp",
            "subprocess",
            "api.comelitgroup.com",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn('print("NETWORK_IO_PERFORMED=false")', text)
        self.assertIn('print("HOME_ASSISTANT_TOUCHED=false")', text)
        self.assertIn('print("DOOR_ACTION_SENT=false")', text)
        self.assertIn('print("SELF_ACTIVATION_SENT=false")', text)
        self.assertIn('print("MEDIA_SIGNALING_SENT=false")', text)


if __name__ == "__main__":
    unittest.main()
