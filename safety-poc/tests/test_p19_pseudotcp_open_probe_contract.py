import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "safety-poc/research/door/v1_5_3"
    / "comelit-v4-persistent-ctpp-door.c"
)
TRANSFORM = (
    ROOT
    / "safety-poc/research/media/v1"
    / "pseudotcp_open_probe_transform.py"
)


def extract_function(text: str, signature: str) -> str:
    start = text.index(signature)
    brace = text.index("{", start + len(signature))
    depth = 0
    in_string = False
    in_char = False
    escaped = False

    for index in range(brace, len(text)):
        ch = text[index]

        if escaped:
            escaped = False
            continue
        if (in_string or in_char) and ch == "\\":
            escaped = True
            continue
        if not in_char and ch == '"':
            in_string = not in_string
            continue
        if not in_string and ch == "'":
            in_char = not in_char
            continue
        if in_string or in_char:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise AssertionError(f"unterminated function: {signature}")


class P19PseudoTcpOpenProbeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_text = SOURCE.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "open-probe.c"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(TRANSFORM),
                    "--source",
                    str(SOURCE),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            cls.transform_stdout = completed.stdout
            cls.candidate = output.read_text(encoding="utf-8")

    def test_transform_is_offline(self):
        self.assertIn("PSEUDOTCP_OPEN_PROBE_TRANSFORM=PASS", self.transform_stdout)
        self.assertIn("NETWORK_IO_PERFORMED=false", self.transform_stdout)
        self.assertIn("DOOR_ACTION_SENT=false", self.transform_stdout)
        self.assertIn("MEDIA_ACTION_SENT=false", self.transform_stdout)

    def test_early_pseudotcp_datagrams_are_preserved_and_replayed(self):
        self.assertNotIn("PSEUDOTCP_RX_BEFORE_START=%u", self.candidate)
        self.assertIn("PSEUDOTCP_RX_BUFFERED=%u LEN=%u", self.candidate)
        self.assertIn("replay_pseudotcp_prestart_packets", self.candidate)
        self.assertIn("PSEUDOTCP_PRESTART_REPLAY_COUNT=%u", self.candidate)
        self.assertIn("PSEUDO_TCP_SYN_RECEIVED", self.candidate)
        self.assertIn("PSEUDO_TCP_ESTABLISHED", self.candidate)
        self.assertIn(
            "PSEUDOTCP_CONNECT_START=SKIPPED_PEER_INITIATED",
            self.candidate,
        )

    def test_pseudotcp_open_is_terminal_success_boundary(self):
        opened = extract_function(
            self.candidate,
            "static void\npseudotcp_opened_cb(",
        )
        self.assertIn('printf("PSEUDOTCP_OPEN=PASS\\n")', opened)
        self.assertIn("PSEUDOTCP_OPEN_PROBE_RESULT=PASS", opened)
        self.assertIn("g_main_loop_quit(loop)", opened)
        self.assertIn("PSEUDOTCP_OPEN_PROBE_APP_SIGNALING_SENT=false", opened)
        self.assertIn("PSEUDOTCP_OPEN_PROBE_SELF_ACTIVATION_SENT=false", opened)
        self.assertIn("PSEUDOTCP_OPEN_PROBE_MEDIA_SIGNALING_SENT=false", opened)
        self.assertIn("PSEUDOTCP_OPEN_PROBE_DOOR_ACTION_SENT=false", opened)
        self.assertNotIn("try_send_echo_ack", opened)
        self.assertNotIn("try_send_uaut_open", opened)
        self.assertNotIn("p12_flush_tx", opened)

    def test_application_callbacks_cannot_advance_vip_protocol(self):
        readable = extract_function(
            self.candidate,
            "static void\npseudotcp_readable_cb(",
        )
        writable = extract_function(
            self.candidate,
            "static void\npseudotcp_writable_cb(",
        )

        for callback in (readable, writable):
            self.assertNotIn("pseudo_tcp_socket_send", callback)
            self.assertNotIn("pseudo_tcp_socket_recv", callback)
            self.assertNotIn("try_send_echo_ack", callback)
            self.assertNotIn("try_send_uaut_open", callback)
            self.assertNotIn("try_parse_initial_echo", callback)
            self.assertNotIn("p12_flush_tx", callback)

        self.assertIn("APP_READABLE_OBSERVED=true", readable)
        self.assertIn("WRITABLE_OBSERVED=true", writable)

    def test_door_entry_points_are_not_installed(self):
        self.assertNotIn(
            "signal(SIGUSR1, v4_door_signal_handler);",
            self.candidate,
        )
        main = extract_function(self.candidate, "int\nmain(void)")
        self.assertNotIn("v4_door_tick_cb", main)
        self.assertIn(
            "PSEUDOTCP_OPEN_PROBE_DOOR_SIGNAL_INSTALLED=false",
            main,
        )

    def test_probe_has_bounded_timeout_and_distinct_timeout_rc(self):
        main = extract_function(self.candidate, "int\nmain(void)")
        timeout_cb = extract_function(
            self.candidate,
            "static gboolean\nopen_probe_timeout_cb(",
        )
        self.assertIn("g_timeout_add_seconds(\n        45,", main)
        self.assertIn("open_probe_timeout_cb", main)
        self.assertNotIn("g_timeout_add_seconds(\n        3300,", main)
        self.assertIn("return 7;", main)
        self.assertIn("PSEUDOTCP_OPEN_PROBE_RESULT=TIMEOUT", timeout_cb)
        self.assertIn("PSEUDOTCP_OPEN_PROBE_SELF_ACTIVATION_SENT=false", timeout_cb)
        self.assertIn("PSEUDOTCP_OPEN_PROBE_MEDIA_SIGNALING_SENT=false", timeout_cb)
        self.assertIn("PSEUDOTCP_OPEN_PROBE_DOOR_ACTION_SENT=false", timeout_cb)

    def test_probe_does_not_add_self_activation_transmit_contract(self):
        self.assertNotIn("PSEUDOTCP_OPEN_PROBE_SELF_ACTIVATION_SENT=true", self.candidate)
        self.assertNotIn("PSEUDOTCP_OPEN_PROBE_MEDIA_SIGNALING_SENT=true", self.candidate)
        self.assertNotIn("PSEUDOTCP_OPEN_PROBE_DOOR_ACTION_SENT=true", self.candidate)

    def test_open_probe_baseline_is_frozen_v153(self):
        self.assertEqual(
            hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            "088e0e23c07404792254f5c18e3f12dbbd499a676bda2d3883988d1d9bb3be6f",
        )


if __name__ == "__main__":
    unittest.main()
