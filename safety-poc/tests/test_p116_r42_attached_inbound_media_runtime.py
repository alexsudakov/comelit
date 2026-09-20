from __future__ import annotations

import ast
from pathlib import Path
import re
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
BUILDER = MEDIA / "ct122_build_p116_r42_attached_media_candidate.sh"
PROMOTER = MEDIA / "ct122_promote_p116_r42_attached_media_candidate.sh"

sys.path.insert(0, str(MEDIA))

import entrance_p106_teardown_state_classification_transform as p106  # noqa: E402
import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402
import entrance_p116_r36_attached_media_trigger_transform as r36  # noqa: E402
import entrance_p116_r37_attached_media_live_readiness_transform as r37  # noqa: E402
import entrance_p116_r42_attached_media_runtime_transform as r42  # noqa: E402
import entrance_p116_r42b_listener_attached_media_transform as r42b  # noqa: E402


class P116R42AttachedInboundMediaRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = DOOR_SOURCE.read_text(encoding="utf-8")
        canonical = p106.transform(base, include_p116=True)
        cls.r35_candidate = r35.transform(canonical)
        cls.r36_candidate = r36.transform(cls.r35_candidate)
        cls.r37_candidate = r37.transform(cls.r36_candidate)
        cls.r42_candidate = r42.transform(cls.r37_candidate)
        cls.r42b_candidate = r42b.transform(base)
        cls.transform_source = TRANSFORM.read_text(encoding="utf-8")
        cls.attached_source = ATTACHED.read_text(encoding="utf-8")
        cls.init_source = INIT.read_text(encoding="utf-8")
        cls.runtime_source = RUNTIME.read_text(encoding="utf-8")
        cls.builder_source = BUILDER.read_text(encoding="utf-8")
        cls.promoter_source = PROMOTER.read_text(encoding="utf-8")

    def test_r42b_composes_from_persistent_listener_and_preserves_door(self) -> None:
        candidate = self.r42b_candidate
        self.assertIn('#define RUN_DIR     "/run/comelit-p2p"', candidate)
        self.assertIn("signal(SIGUSR1, v4_door_signal_handler);", candidate)
        self.assertIn("v4_door_tick_cb", candidate)
        for marker in (
            "V4_DOOR_EXISTING_CTPP_REUSED=true",
            "V4_DOOR_OPERATION_WRITES_SENT=5",
            "V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
            "V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
            "V4_RING_LISTENER_READY=true",
            "R42_LISTENER_DOOR_SIGNAL_PRESERVED=true",
            "R42_LISTENER_RTP_LIFETIME_RESET=true",
            "R42_ATTACHED_MEDIA_ACTIVE=true",
            "R42_MEDIA_CHANNEL_CLOSED=true",
        ):
            self.assertIn(marker, candidate)
        for forbidden in (
            "/run/comelit-media",
            "signal(SIGUSR1, SIG_IGN);",
            "ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false",
            "entrance_self_activation",
            "P12_TX_ENTRANCE_SELF_ACTIVATION",
        ):
            self.assertNotIn(forbidden, candidate)

    def test_r42b_generated_source_is_deterministic(self) -> None:
        base = DOOR_SOURCE.read_text(encoding="utf-8")
        self.assertEqual(self.r42b_candidate, r42b.transform(base))

    def test_r42b_rebinds_r35_rtp_hook_to_listener_lifetime_reset(self) -> None:
        candidate = self.r42b_candidate
        self.assertEqual(candidate.count("r42_listener_rtp_arm(armed);"), 1)
        self.assertNotIn(
            "p80_media_forwarding_enabled = armed ? TRUE : FALSE;",
            candidate,
        )
        self.assertIn("r42_listener_rtp_reset_lifetime", candidate)
        self.assertIn("p80_video_profile_seen = FALSE", candidate)
        self.assertIn("p80_audio_profile_seen = FALSE", candidate)

    def test_transform_composes_only_after_r37(self) -> None:
        self.assertIn("R42_ATTACHED_INBOUND_MEDIA_RUNTIME_BEGIN", self.r42_candidate)
        with self.assertRaises(RuntimeError):
            r42.transform(self.r36_candidate)
        with self.assertRaises(RuntimeError):
            r42.transform(self.r42_candidate)

    def test_allocator_forward_declaration_precedes_first_r42_call(self) -> None:
        declaration = r42._ALLOCATOR_FORWARD_DECL
        call = r42._ALLOCATOR_FIRST_R42_CALL
        definition = r42._ALLOCATOR_DEFINITION
        self.assertEqual(self.r42_candidate.count(declaration), 1)
        self.assertLess(
            self.r42_candidate.index(declaration),
            self.r42_candidate.index(call),
        )
        self.assertGreater(
            self.r42_candidate.index(definition),
            self.r42_candidate.index(declaration),
        )

    def test_allocator_order_gate_rejects_missing_forward_declaration(self) -> None:
        broken = self.r42_candidate.replace(
            r42._ALLOCATOR_FORWARD_DECL + "\n\n",
            "",
            1,
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "R42_ALLOCATOR_FORWARD_DECL_GATE=FAIL",
        ):
            r42._gate_allocator_declaration_order(broken)

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

    def test_ambiguous_teardown_blocks_next_media_channel(self) -> None:
        runtime = self.r42_candidate.split(
            "/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_BEGIN */", 1
        )[1].split("/* R42_ATTACHED_INBOUND_MEDIA_RUNTIME_END */", 1)[0]
        self.assertIn("r42_media_channel_id != 0u", runtime)
        self.assertIn("R42_STALE_MEDIA_CHANNEL_BLOCKED=true", runtime)
        self.assertIn("r42_media_stage != R42_MEDIA_IDLE", runtime)
        self.assertIn("r42_media_stage != R42_MEDIA_CLOSED", runtime)

    def test_ct122_builder_requires_two_identical_offline_musl_builds(self) -> None:
        source = self.builder_source
        self.assertGreaterEqual(source.count("--network none"), 1)
        self.assertIn("comelit-v4-r42b-candidate-a", source)
        self.assertIn("comelit-v4-r42b-candidate-b", source)
        self.assertIn('[[ "$BUILD_A_SHA" == "$BUILD_B_SHA" ]]', source)
        self.assertIn('cmp -s "$BUILD_A" "$BUILD_B"', source)
        self.assertIn("REPRODUCIBLE_BINARY_SHA_GATE=PASS", source)
        self.assertIn("REPRODUCIBLE_SOURCE_SHA_GATE=PASS", source)
        self.assertIn("REPRODUCIBLE_SOURCE_CMP_GATE=PASS", source)
        self.assertIn("REPRODUCIBLE_BINARY_CMP_GATE=PASS", source)
        self.assertIn("LISTENER_LINEAGE_GATE=PASS", source)
        self.assertIn("DOOR_RUNTIME_SOURCE_GATE=PASS", source)
        self.assertIn("DOOR_RUNTIME_BINARY_GATE=PASS", source)
        self.assertIn(
            "entrance_p116_r42b_listener_attached_media_transform.py",
            source,
        )
        self.assertNotIn(
            "entrance_p106_teardown_state_classification_transform.py",
            source,
        )
        self.assertIn("CANDIDATE_EXECUTED=false", source)
        self.assertIn("COMELIT_NETWORK_REQUESTS=0", source)
        self.assertIn(
            "cc -O2 -g -Wall -Wextra -Wl,--as-needed",
            source,
        )
        self.assertNotIn("-Werror", source)
        self.assertNotIn("curl ", source)
        self.assertNotIn("wget ", source)

    def test_ct122_builder_compiles_both_builds_from_one_canonical_input_name(
        self,
    ) -> None:
        source = self.builder_source
        # Each build_once call site passes the source-name argument as
        # either a bare "$VAR" reference or a "$(basename "$VAR")"
        # substitution; capture whichever shape is actually used so the
        # regression catches per-source filenames without hardcoding one
        # implementation.
        call_site_pattern = re.compile(
            r'build_once\s+"(\$\w+|\$\(basename "\$\w+"\))"'
        )
        call_args = call_site_pattern.findall(source)
        self.assertEqual(
            len(call_args),
            2,
            "expected exactly two build_once invocations with a "
            "source-name first argument",
        )
        build_a_arg, build_b_arg = call_args
        self.assertEqual(
            build_a_arg,
            build_b_arg,
            "both build_once invocations must compile from the same "
            "canonical staged source name, otherwise the compiled "
            "filename baked into DWARF/BuildID drifts between builds",
        )
        self.assertNotIn("SOURCE_A", build_a_arg)
        self.assertNotIn("SOURCE_B", build_b_arg)

        # The staged name must actually be handed to the container as SRC,
        # which build_once forwards from its first positional argument.
        self.assertIn('-e SRC="$src_name"', source)
        self.assertIn("local src_name=$1", source)

    def test_ct122_promotion_rechecks_source_binary_and_reproducible_peer(self) -> None:
        source = self.promoter_source
        for required in (
            "EXPECTED_SOURCE_SHA256",
            "EXPECTED_SHA256",
            "REPRODUCIBLE_PEER",
            'cmp -s "$CANDIDATE" "$REPRODUCIBLE_PEER"',
            "R42_PROMOTION=PASS",
            "P116_R42_BUILD_INFO.txt",
            "candidate_executed=false",
            "comelit_network_requests=0",
            "ha_deploy_performed=false",
        ):
            self.assertIn(required, source)
        self.assertIn("GIT_COMMIT_PERFORMED=false", source)
        self.assertIn("GIT_PUSH_PERFORMED=false", source)
        self.assertIn(
            "phase=P116_R42B_LISTENER_ATTACHED_INBOUND_MEDIA",
            source,
        )
        self.assertIn(
            "listener_lineage=frozen_v1_5_7_persistent_listener",
            source,
        )
        self.assertIn("door_sigusr1_preserved=true", source)
        self.assertIn("door_tick_preserved=true", source)
        self.assertIn("V4_DOOR_EXISTING_CTPP_REUSED=true", source)

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

    def test_door_service_is_blocked_during_attached_media(self) -> None:
        self.assertIn(
            "supervisor.media_paused or supervisor.attached_media_busy",
            self.init_source,
        )
        self.assertIn(
            "media lifecycle owns the Comelit connection",
            self.init_source,
        )

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
