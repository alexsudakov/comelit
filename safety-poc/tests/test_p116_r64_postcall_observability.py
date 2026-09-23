from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
SOURCE = (
    ROOT
    / "safety-poc"
    / "research"
    / "door"
    / "v1_5_7"
    / "comelit-v4-persistent-ctpp-door.c"
)
RUNTIME = ROOT / "custom_components" / "comelit" / "runtime.py"

if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

import entrance_p116_r63_gate_peer_tap_actuation_transform as r63
import entrance_p116_r64_postcall_observability_transform as r64


class P116R64PostCallObservabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.r63 = r63.transform(cls.source)
        cls.generated_a = r64.transform(cls.source)
        cls.generated_b = r64.transform(cls.source)
        cls.runtime = RUNTIME.read_text(encoding="utf-8")

    def test_transform_is_deterministic_and_preserves_r63(self) -> None:
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertIn("/* R63_GATE_PEER_TAP_BEGIN */", self.generated_a)
        self.assertIn(r64.BEGIN, self.generated_a)
        self.assertIn(r64.END, self.generated_a)

    def test_r64_adds_no_protocol_write_or_retry_surface(self) -> None:
        writers = (
            "p12_queue_bytes(",
            "p12_queue_vip_frame(",
            "pseudo_tcp_socket_send(",
            "nice_agent_send(",
            "r35_send_stop(",
            "r35_send_open(",
            "g_timeout_add(",
            "g_timeout_add_seconds(",
        )
        for needle in writers:
            with self.subTest(needle=needle):
                self.assertEqual(
                    self.generated_a.count(needle),
                    self.r63.count(needle),
                )
        self.assertEqual(
            self.generated_a.count("signal(SIGUSR1, v4_door_signal_handler);"),
            self.r63.count("signal(SIGUSR1, v4_door_signal_handler);"),
        )

    def test_post_call_snapshot_is_after_authoritative_r58_close(self) -> None:
        close_function = self.generated_a.split(
            "static void\nr58_stop_publish_closed(void)", 1
        )[1].split("/* R58_STOP_CLEANUP_END */", 1)[0]
        closed = close_function.index('printf("R58_STOP_CLOSED=true\\n");')
        channel_close_call = close_function.index(
            "r42_finish_media_channel_close();",
            closed,
        )
        snapshot_call = close_function.index(
            "r64_publish_post_call_snapshot();",
            channel_close_call,
        )
        self.assertLess(closed, channel_close_call)
        self.assertLess(channel_close_call, snapshot_call)

        r42_close_function = self.generated_a.split(
            "static void\nr42_finish_media_channel_close(void)", 1
        )[1].split("}", 1)[0]
        self.assertIn(
            'printf("R42_MEDIA_CHANNEL_CLOSED=true\\n");',
            r42_close_function,
        )
        for marker in (
            "R64_POST_CALL_REMOTE_RELEASE_OBSERVED=%s",
            "R64_POST_CALL_CAPABILITY_CLEARED_OBSERVED=%s",
            "R64_POST_CALL_TX_STATE=%s",
            "R64_POST_CALL_TX_SUBJECT=%s",
            "R64_POST_CALL_TX_PENDING=%s",
            "R64_POST_CALL_CALL_READY=%s",
            "R64_POST_CALL_PSEUDOTCP_OPEN=%s",
            "R64_POST_CALL_SNAPSHOT=true",
        ):
            self.assertIn(marker, self.generated_a)

    def test_terminal_snapshot_precedes_existing_r57_exit_summary(self) -> None:
        terminal = self.generated_a.index("r64_publish_terminal_snapshot();")
        existing = self.generated_a.index(
            "p116_emit_native_exit_summary(failed);",
            terminal,
        )
        self.assertLess(terminal, existing)
        for marker in (
            "R64_TERMINAL_TX_STATE=%s",
            "R64_TERMINAL_TX_SUBJECT=%s",
            "R64_TERMINAL_TX_PENDING=%s",
            "R64_TERMINAL_CALL_READY=%s",
            "R64_TERMINAL_PSEUDOTCP_OPEN=%s",
            "R64_TERMINAL_SNAPSHOT=true",
        ):
            self.assertIn(marker, self.generated_a)

    def test_protocol_stop_discriminators_are_latched_before_handlers(self) -> None:
        cap_note = self.generated_a.index("r64_note_capability_cleared();")
        cap_handle = self.generated_a.index(
            "r37_handle_capability_cleared(",
            cap_note,
        )
        release_note = self.generated_a.index("r64_note_remote_release();")
        release_handle = self.generated_a.index(
            "r37_handle_remote_release(",
            release_note,
        )
        self.assertLess(cap_note, cap_handle)
        self.assertLess(release_note, release_handle)

    def test_existing_pseudotcp_close_discriminators_survive(self) -> None:
        self.assertIn("PSEUDOTCP_CLOSED_BEFORE_OPEN=true", self.generated_a)
        self.assertIn("PSEUDOTCP_CLOSED_AFTER_OPEN=true", self.generated_a)

    def test_ha_runtime_retains_only_bounded_snapshot_surface(self) -> None:
        for needle in (
            '"R64_",',
            '"R64_POST_CALL_TX_STATE": _R54_TX_STATES',
            '"R64_TERMINAL_TX_STATE": _R54_TX_STATES',
            '"R64_POST_CALL_TX_SUBJECT": _R54_TX_SUBJECTS',
            '"R64_TERMINAL_TX_SUBJECT": _R54_TX_SUBJECTS',
            '"PSEUDOTCP_CLOSED_BEFORE_OPEN": "PSEUDOTCP_CLOSED_BEFORE_OPEN"',
            '"PSEUDOTCP_CLOSED_AFTER_OPEN": "PSEUDOTCP_CLOSED_AFTER_OPEN"',
            '"post_call_observability": {',
            "def _record_r64_snapshot_marker",
            'line == "R64_POST_CALL_SNAPSHOT=true"',
        ):
            self.assertIn(needle, self.runtime)

    def test_r64_does_not_change_gate_or_door_safety_contract(self) -> None:
        for needle in (
            "V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
            "V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
            'V4_DOOR_TARGET_FILE RUN_DIR "/door-target"',
        ):
            self.assertEqual(
                self.generated_a.count(needle),
                self.r63.count(needle),
            )


if __name__ == "__main__":
    unittest.main()
