from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
DOOR_SOURCE = (
    ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
)
TRANSFORM = MEDIA / "entrance_p116_r42_attached_media_runtime_transform.py"
ATTACHED = ROOT.parent / "custom_components" / "comelit" / "attached_media.py"
INIT = ROOT.parent / "custom_components" / "comelit" / "__init__.py"
RUNTIME = ROOT.parent / "custom_components" / "comelit" / "runtime.py"

sys.path.insert(0, str(MEDIA))

import entrance_p106_teardown_state_classification_transform as p106  # noqa: E402
import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402
import entrance_p116_r36_attached_media_trigger_transform as r36  # noqa: E402
import entrance_p116_r37_attached_media_live_readiness_transform as r37  # noqa: E402
import entrance_p116_r42_attached_media_runtime_transform as r42  # noqa: E402


class P116R42AttachedInboundMediaRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = DOOR_SOURCE.read_text(encoding="utf-8")
        canonical = p106.transform(base, include_p116=True)
        cls.r35_candidate = r35.transform(canonical)
        cls.r36_candidate = r36.transform(cls.r35_candidate)
        cls.r37_candidate = r37.transform(cls.r36_candidate)
        cls.r42_candidate = r42.transform(cls.r37_candidate)
        cls.transform_source = TRANSFORM.read_text(encoding="utf-8")
        cls.attached_source = ATTACHED.read_text(encoding="utf-8")
        cls.init_source = INIT.read_text(encoding="utf-8")
        cls.runtime_source = RUNTIME.read_text(encoding="utf-8")

    def test_transform_composes_only_after_r37(self) -> None:
        self.assertIn("R42_ATTACHED_INBOUND_MEDIA_RUNTIME_BEGIN", self.r42_candidate)
        with self.assertRaises(RuntimeError):
            r42.transform(self.r36_candidate)
        with self.assertRaises(RuntimeError):
            r42.transform(self.r42_candidate)

    def test_r42_intercepts_before_r36_placeholder(self) -> None:
        r42_index = self.r42_candidate.index("/* R42_ATTACHED_TRIGGER_BEGIN */")
        r36_index = self.r42_candidate.index("/* R36_WIRING_TRIGGER_BEGIN */")
        self.assertLess(r42_index, r36_index)
        trigger = self.r42_candidate[r42_index:r36_index]
        self.assertIn("r42_queue_media_channel_open", trigger)
        self.assertIn("continue;", trigger)
        self.assertIn("R42_AUTOMATIC_RETRY=false", trigger)

    def test_r42_allocates_runtime_rtpc_channel_not_capture_literal(self) -> None:
        source = self.r42_candidate.split(
            "/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_BEGIN */", 1
        )[1].split("/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_END */", 1)[0]
        self.assertIn("v4_allocate_channel_id", source)
        self.assertIn('memcpy(body + 8, "RTPC", 4)', source)
        self.assertIn("body[14] = 1", source)
        self.assertIn("r35_allocate_media_rx_channel", source)
        for capture_literal in ("0x0C4A", "0x4A5A", "0xCA5A"):
            self.assertNotIn(capture_literal, source)

    def test_r42_open_profile_matches_physical_capture(self) -> None:
        source = self.transform_source.lower()
        for assignment in (
            "src.max_rtp_payload = 0xffffu",
            "src.channel_profile_word = 0u",
            "src.profile_halfwords[0] = 0x0320u",
            "src.profile_halfwords[1] = 0x01e0u",
            "src.profile_halfwords[2] = 0x0140u",
            "src.profile_halfword_3 = 0x00f0u",
            "src.profile_byte_4 = 0x10u",
        ):
            self.assertIn(assignment, source)
        self.assertIn("src.form = r35_form_tunnel", source)
        self.assertIn("src.video_request = 1", source)

    def test_r42_arms_rtp_only_after_mediareq_open_tx_completion(self) -> None:
        candidate = self.r42_candidate
        case = candidate.split("case P12_TX_R35_MEDIA_OPEN:", 1)[1].split(
            "case P12_TX_R35_MEDIA_STOP:", 1
        )[0]
        self.assertIn("r42_activate_after_mediareq_open", case)
        runtime = candidate.split(
            "/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_BEGIN */", 1
        )[1].split("/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_END */", 1)[0]
        activation = runtime.split("r42_activate_after_mediareq_open", 1)[1]
        self.assertIn("r35_enable_rtp", activation)
        self.assertIn("R42_ATTACHED_MEDIA_ACTIVE=true", activation)

    def test_r42_stop_closes_same_runtime_channel_after_close_response(self) -> None:
        candidate = self.r42_candidate
        stop_case = candidate.split("case P12_TX_R35_MEDIA_STOP:", 1)[1].split(
            "case P12_TX_R42_MEDIA_CHANNEL_CLOSE:", 1
        )[0]
        self.assertIn("r42_queue_media_channel_close", stop_case)

        close_tx_case = candidate.split(
            "case P12_TX_R42_MEDIA_CHANNEL_CLOSE:", 1
        )[1].split("default:", 1)[0]
        self.assertIn(
            "r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_WAIT",
            close_tx_case,
        )
        self.assertIn("R42_MEDIA_CHANNEL_CLOSE_SENT=true", close_tx_case)
        self.assertNotIn("r42_finish_media_channel_close()", close_tx_case)

        trigger = candidate.split(
            "/* R42_ATTACHED_TRIGGER_BEGIN */", 1
        )[1].split("/* R42_ATTACHED_TRIGGER_END */", 1)[0]
        self.assertIn("R42_MEDIA_CHANNEL_CLOSE_WAIT", trigger)
        self.assertIn("p12_parse_control_response", trigger)
        self.assertIn("r42_media_channel_id", trigger)
        self.assertIn("r42_response_word == 0", trigger)
        self.assertIn("r42_finish_media_channel_close()", trigger)
        self.assertIn("R42_MEDIA_CHANNEL_CLOSED=true", candidate)

    def test_one_attempt_per_call_generation_and_no_retry_loop(self) -> None:
        source = self.r42_candidate.split(
            "/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_BEGIN */", 1
        )[1].split("/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_END */", 1)[0].lower()
        self.assertIn(
            "r42_attempted_call_generation == g_r35_session.call_generation",
            source,
        )
        self.assertIn(
            "r42_attempted_call_generation = g_r35_session.call_generation",
            source,
        )
        self.assertNotIn("g_timeout_add", source)
        self.assertNotIn("for (", source)
        self.assertNotIn("while (", source)

    def test_attached_python_bridge_never_pauses_listener_or_bootstraps_cloud(self) -> None:
        source = self.attached_source
        self.assertIn('"ownership": "attached_inbound_session"', source)
        self.assertIn('"listener_paused": False', source)
        self.assertIn("async_wait_attached_media_open", source)
        self.assertIn("async_stop_attached_media", source)
        self.assertNotIn("async_pause_for_media", source)
        self.assertNotIn("async_negotiate_p2p", source)
        self.assertNotIn("ComelitOAuthManager", source)
        ast.parse(source)

    def test_real_and_synthetic_ring_media_lifecycles_are_separate(self) -> None:
        self.assertIn("ComelitAttachedRingMediaTransport(runtime)", self.init_source)
        self.assertIn("ComelitAttachedRingMediaSession(attached_transport)", self.init_source)
        self.assertIn(
            "runtime.set_synthetic_ring_media_coordinator(synthetic_ring_media)",
            self.init_source,
        )
        self.assertIn("media_manager", self.init_source)
        self.assertIn("attached_session", self.init_source)
        ast.parse(self.init_source)
        ast.parse(self.runtime_source)

    def test_manual_camera_is_blocked_while_attached_media_owns_listener(self) -> None:
        media_session = (
            ROOT.parent / "custom_components" / "comelit" / "media_session.py"
        ).read_text(encoding="utf-8")
        supervisor = (
            ROOT.parent / "custom_components" / "comelit" / "supervisor.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'getattr(self._listener, "attached_media_busy", False)',
            media_session,
        )
        self.assertIn(
            'ComelitMediaSessionError("attached_inbound_media_busy")',
            media_session,
        )
        self.assertIn("def attached_media_busy(self)", supervisor)
        self.assertIn("return self._runtime.attached_media_busy", supervisor)
        self.assertIn("R42_MEDIA_CHANNEL_ALLOCATED=true", self.runtime_source)
        self.assertIn("self._attached_media_busy.set()", self.runtime_source)
        self.assertIn("self._attached_media_busy.clear()", self.runtime_source)

    def test_runtime_exposes_bounded_sigusr2_attached_stop(self) -> None:
        tree = ast.parse(self.runtime_source)
        cls = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ComelitRingRuntime"
        )
        methods = {
            node.name: ast.unparse(node)
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("async_wait_attached_media_open", methods)
        self.assertIn("async_stop_attached_media", methods)
        stop = methods["async_stop_attached_media"]
        self.assertIn("signal.SIGUSR2", stop)
        self.assertNotIn("while ", stop)
        self.assertNotIn("SIGUSR1", stop)


if __name__ == "__main__":
    unittest.main()
