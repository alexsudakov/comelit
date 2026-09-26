#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SAFETY = ROOT / "safety-poc"
MEDIA = SAFETY / "research" / "media" / "v1"
SOURCE = SAFETY / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_msl_v1_idle_listener_media_transform.py"
RUNNER = MEDIA / "ct120_run_msl_v1_variant_b_live.sh"

sys.path.insert(0, str(MEDIA))

import entrance_msl_v1_idle_listener_media_transform as msl_b  # noqa: E402


COUNTERS = (
    "MSL_B_CLOUD_NEGOTIATION_COUNT",
    "MSL_B_ICE_BOOTSTRAP_COUNT",
    "MSL_B_PSEUDOTCP_OPEN_COUNT",
    "MSL_B_CTPP_REGISTRATION_COUNT",
    "MSL_B_MEDIA_SESSION_COUNT",
    "MSL_B_SECOND_MEDIA_SESSION",
    "MSL_B_LISTENER_PROCESS_PID",
    "MSL_B_RECONNECT_COUNT_BEFORE",
    "MSL_B_RECONNECT_COUNT_AFTER",
    "MSL_B_RECONNECT_COUNT_DELTA",
    "MSL_B_MEDIA_RX_ACTIVE",
    "MSL_B_MEDIA_RX_INACTIVE_AFTER_CLOSE",
    "MSL_B_VIDEO_RTP_PACKETS",
    "MSL_B_SPS_COUNT",
    "MSL_B_TUNNEL_PRESERVED",
)


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_MSL_B_SYMBOL_RE = re.compile(r"\bmsl_b_[a-z0-9_]+\b")
_MSL_B_PRECEDING_WORD_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\Z")
_MSL_B_NON_DECL_PRECEDING_WORDS = {"if", "while", "return", "else", "do", "switch", "for", "sizeof"}
_MSL_B_NON_DECL_PRECEDING_CHARS = set("(!=&|,?:;{}+-*/<>[]~^%")


def msl_b_symbol_declaration_positions(candidate: str) -> dict[str, tuple[int, int]]:
    """Map every lowercase msl_b_* identifier to (first_declaration_pos, first_occurrence_pos).

    A position is treated as a declaration site when the token immediately
    preceding the identifier (skipping whitespace) looks like a C type name
    rather than an operator, keyword, or nothing (a bare call statement).
    first_declaration_pos is -1 when no occurrence looks like a declaration.
    """
    occurrences: dict[str, list[int]] = {}
    for match in _MSL_B_SYMBOL_RE.finditer(candidate):
        occurrences.setdefault(match.group(0), []).append(match.start())

    result: dict[str, tuple[int, int]] = {}
    for symbol, starts in occurrences.items():
        starts.sort()
        decl_pos = -1
        for pos in starts:
            stripped = candidate[:pos].rstrip()
            if not stripped or stripped[-1] in _MSL_B_NON_DECL_PRECEDING_CHARS:
                continue
            word_match = _MSL_B_PRECEDING_WORD_RE.search(stripped)
            if not word_match or word_match.group(1) in _MSL_B_NON_DECL_PRECEDING_WORDS:
                continue
            decl_pos = pos
            break
        result[symbol] = (decl_pos, starts[0])
    return result


class MslV1IdleListenerMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = SOURCE.read_text(encoding="utf-8")
        cls.generated_a = msl_b.transform(cls.base)
        cls.generated_b = msl_b.transform(cls.base)
        cls.region = cls.generated_a.split(msl_b.BEGIN, 1)[1].split(msl_b.END, 1)[0]
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_transform_is_deterministic(self) -> None:
        a = sha_text(self.generated_a)
        b = sha_text(self.generated_b)
        mutated_source = self.base.replace('#define STOP_FILE   RUN_DIR "/stop"', '#define STOP_FILE   RUN_DIR "/halt"', 1)
        with self.assertRaises(RuntimeError):
            msl_b.transform(mutated_source)
        self.assertEqual(a, b)
        print(f"MSL_B_TRANSFORM_DETERMINISTIC=true REAL={a} MUTATED=ANCHOR_FAIL")

    def test_control_surface_and_ready_preconditions(self) -> None:
        for marker in (
            '#define MSL_B_START_FILE RUN_DIR "/msl-b-start-idle-media"',
            '#define MSL_B_STOP_FILE  RUN_DIR "/msl-b-stop-idle-media"',
            "msl_b_ready_now",
            "v4_listener_ready && pseudotcp_open && v4_registered && v4_ctpp_channel_id != 0",
            "msl_b_control_poll_cb",
            "g_timeout_add(\n        100,\n        msl_b_control_poll_cb",
        ):
            self.assertIn(marker, self.generated_a)

    def test_no_new_session_path_added(self) -> None:
        for forbidden in (
            "nice_agent_new",
            "pseudo_tcp_socket_new",
            "P12_TX_V4_OPEN_CTPP",
            "P12_TX_AUTH",
            "curl",
            "oauth",
        ):
            self.assertNotIn(forbidden, self.region)
        self.assertIn("MSL_B_SECOND_UPSTREAM_SESSION=false", self.region)
        print("MSL_B_NO_NEW_SESSION_PATH=true REAL=listener_overlay MUTATED=forbidden_token_scan")

    def test_no_door_gate_path_added(self) -> None:
        door_gate_calls = (
            "P12_TX_V4_DOOR_WRITE",
            "v4_door_signal_handler",
            "v4_queue_door",
            "V4_GATE",
        )
        for token in door_gate_calls:
            self.assertNotIn(token, self.region)
        print("MSL_B_NO_DOOR_GATE_PATH=true REAL=overlay_region MUTATED=door_gate_token_scan")

    def test_ring_collision_and_duplicate_start_fail_closed(self) -> None:
        for marker in (
            "g_r35_session.call_transaction_alive || r42_media_stage == R42_MEDIA_ACTIVE",
            "MSL_B_RING_COLLISION_FAIL_CLOSED=true",
            "MSL_B_DUPLICATE_START_REJECTED=true",
            "msl_b_ring_collision_rejected_count++",
            "msl_b_duplicate_start_rejected_count++",
        ):
            self.assertIn(marker, self.region)
        print("MSL_B_RING_COLLISION_FAIL_CLOSED=true REAL=reject_busy MUTATED=removed_collision_predicate")

    def test_media_open_close_serialized_through_p12_completion(self) -> None:
        open_case = self.generated_a.split("case P12_TX_R42_MEDIA_CHANNEL_OPEN:", 1)[1].split(
            "case P12_TX_R35_MEDIA_OPEN:", 1
        )[0]
        # R42 channel-open completion now starts the reused pre-0x001A RTPC
        # control sequence (open_2) instead of jumping straight to
        # self-activation; msl_b_queue_idle_self_activation is reachable
        # only from the post-000A ACK cycle, verified separately below.
        self.assertIn("msl_b_queue_rtpc_open_2()", open_case)
        self.assertNotIn("msl_b_queue_idle_self_activation()", open_case)
        self.assertNotIn("r42_queue_mediareq_open())", open_case.split("if (msl_b_idle_state", 1)[0])
        activation_case = self.generated_a.split("case P12_TX_MSL_B_IDLE_SELF_ACTIVATION:", 1)[1].split(
            "case P12_TX_R35_MEDIA_OPEN:", 1
        )[0]
        self.assertIn("msl_b_arm_device_ack_wait()", activation_case)
        self.assertNotIn("msl_b_activate_idle_media", activation_case)
        close_case = self.generated_a.split("case P12_TX_R42_MEDIA_CHANNEL_CLOSE:", 1)[1].split(
            "case P12_TX_R54_INVITE_ACK:", 1
        )[0]
        self.assertIn("r42_finish_media_channel_close()", close_case)

    def test_idle_media_active_is_gated_on_structural_ack_with_flip_proof(self) -> None:
        tx_case = self.generated_a.split("case P12_TX_MSL_B_IDLE_SELF_ACTIVATION:", 1)[1].split("break;", 1)[0]
        ack_handler = self.generated_a.split("msl_b_handle_device_ack_001a(guint32 request_id", 1)[1].split(
            "\n}\n", 1
        )[0]
        self.assertIn("msl_b_arm_device_ack_wait()", tx_case)
        self.assertNotIn("MSL_B_MEDIA_ACTIVE=true", tx_case)
        self.assertIn("msl_b_ack_matches_source", ack_handler)
        self.assertIn("msl_b_activate_idle_media_after_ack()", ack_handler)
        self.assertIn("MSL_B_DEVICE_STRUCTURAL_ACK_DERIVED_FROM_TX_COMPLETION=false", self.generated_a)

        mutated = self.generated_a.replace(
            "(void)msl_b_arm_device_ack_wait();", "printf(\"MSL_B_MEDIA_ACTIVE=true\\n\");", 1
        )
        mutated_case = mutated.split("case P12_TX_MSL_B_IDLE_SELF_ACTIVATION:", 1)[1].split("break;", 1)[0]
        self.assertIn("MSL_B_MEDIA_ACTIVE=true", mutated_case)
        print(
            "MSL_B_ACK_GATED_MEDIA_ACTIVE=true "
            "REAL=tx_completion_arms_ack_wait "
            "MUTATED=tx_completion_reports_media_active"
        )

    def test_receive_path_registered_before_media_active_with_flip_proof(self) -> None:
        activation = self.generated_a.split("msl_b_activate_idle_media_after_ack(void)\n{", 1)[1].split(
            "\n}\n", 1
        )[0]
        register_idx = activation.index("msl_b_register_receive_path()")
        arm_idx = activation.index("r42_listener_rtp_arm(1);")
        active_idx = activation.index('printf("MSL_B_MEDIA_ACTIVE=true\\n");')
        self.assertLess(register_idx, arm_idx)
        self.assertLess(arm_idx, active_idx)
        self.assertIn("p80_loopback_socket(&p80_video_rtp_target, P80_VIDEO_RTP_PORT)", self.generated_a)
        self.assertIn("p80_loopback_socket(&p80_audio_rtp_target, P80_AUDIO_RTP_PORT)", self.generated_a)

        mutated_activation = activation.replace(
            "msl_b_register_receive_path()", "msl_b_register_receive_path_MUTATED()", 1
        )
        self.assertNotIn("msl_b_register_receive_path()", mutated_activation)
        print(
            "MSL_B_RECEIVE_PATH_REGISTERED_BEFORE_MEDIA_ACTIVE=true "
            f"REAL=register:{register_idx}<arm:{arm_idx}<active:{active_idx} "
            "MUTATED=registration_call_removed"
        )

    def test_pre_001a_sequence_ordered_with_flip_proof(self) -> None:
        # Proven order reused from entrance_p78_rtpc_media_live_stage_transform.py
        # and entrance_p97_complete_post_000a_ack_cycle_transform.py: device
        # RTPC OPEN -> client RESPONSE -> device RESPONSE(s) -> client
        # 0x000A -> device 0x000A -> post-000A ACK cycle -> only then
        # 0x001A.  Checked via each stage's state-machine dependency chain
        # (predecessor precondition before successor state-write), since
        # function *definitions* and *call sites* are legitimately
        # interleaved in the generated source.
        step_chain = (
            ("msl_b_queue_rtpc_open_2", "MSL_B_IDLE_STATE_CHANNEL_OPEN_TX", "MSL_B_IDLE_STATE_OPEN2_TX"),
            ("msl_b_queue_rtpc_client_response", "MSL_B_IDLE_STATE_WAIT_DEVICE_OPEN", "MSL_B_IDLE_STATE_CLIENT_RESPONSE_TX"),
            ("msl_b_queue_client_000a", "MSL_B_IDLE_STATE_WAIT_DEVICE_RESPONSES", "MSL_B_IDLE_STATE_CLIENT_000A_TX"),
            ("msl_b_queue_device_000a_ack", "MSL_B_IDLE_STATE_WAIT_DEVICE_000A", "MSL_B_IDLE_STATE_DEVICE_000A_ACK_TX"),
            ("msl_b_queue_idle_self_activation", "MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A", "MSL_B_IDLE_STATE_SELF_ACTIVATION_TX"),
        )

        def fn_body(source: str, name: str) -> str:
            match = re.search(rf"\b{re.escape(name)}\([^;{{}}]*\)\n\{{", source)
            self.assertIsNotNone(match, name)
            return source[match.end():].split("\n}\n", 1)[0]

        for fn_name, predecessor, successor in step_chain:
            body = fn_body(self.generated_a, fn_name)
            self.assertIn(predecessor, body, fn_name)
            self.assertLess(
                body.index(predecessor),
                body.index(f"msl_b_idle_state = {successor};"),
                fn_name,
            )

        # Clock markers also fire in the proven order, in the generated
        # source's TX-completion/frame-hook sites (a single generated file,
        # single execution thread -- source order of the reused primitive
        # call chain is the runtime order here).
        state_enum_region = self.generated_a.split(
            "typedef enum {\n    MSL_B_IDLE_STATE_IDLE = 0,", 1
        )[1].split("} MslBIdleMediaState;", 1)[0]
        ordered_states = [step[1] for step in step_chain] + [step_chain[-1][2]]
        real_positions = [state_enum_region.index(s) for s in ordered_states]
        self.assertEqual(real_positions, sorted(real_positions))

        # Flip proof: removing the predecessor precondition from one
        # mid-chain step (device 0x000A ACK) must break the ordering proof.
        device_000a_ack_body = fn_body(self.generated_a, "msl_b_queue_device_000a_ack")
        mutated_full = self.generated_a.replace(
            device_000a_ack_body,
            device_000a_ack_body.replace("MSL_B_IDLE_STATE_WAIT_DEVICE_000A", "MSL_B_IDLE_STATE_IDLE"),
            1,
        )
        mutated_body = fn_body(mutated_full, "msl_b_queue_device_000a_ack")
        self.assertNotIn("MSL_B_IDLE_STATE_WAIT_DEVICE_000A", mutated_body)
        print(
            "MSL_B_PRE_001A_SEQUENCE_ORDER=true "
            f"REAL={ordered_states} "
            "MUTATED=device_000a_ack_precondition_removed"
        )

    def test_pre_rtpc_activation_sequence_ordered_with_flip_proof(self) -> None:
        # V3 hypothesis: RTPC must not begin until the proven pre-RTPC
        # self-activation preamble (0x0028 -> client 0x0008 -> device 0x0008
        # -> device 0x0002, each with its structural ACK) completes inside
        # the already-READY listener session.  Checked the same way as the
        # pre-001A chain: each stage's precondition names its exact
        # predecessor state and its state-write names its exact successor.
        activation_step_chain = (
            ("msl_b_queue_preamble_client_0008", "MSL_B_IDLE_STATE_WAIT_0028_ACK", "MSL_B_IDLE_STATE_PREAMBLE_CLIENT_0008_TX"),
            ("msl_b_queue_ack_device_0008", "MSL_B_IDLE_STATE_WAIT_DEVICE_0008", "MSL_B_IDLE_STATE_ACK_DEVICE_0008_TX"),
            ("msl_b_queue_ack_device_0002", "MSL_B_IDLE_STATE_WAIT_DEVICE_0002", "MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX"),
            ("msl_b_queue_rtpc_open_1", "MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX", "MSL_B_IDLE_STATE_CHANNEL_OPEN_TX"),
        )

        def fn_body(source: str, name: str) -> str:
            match = re.search(rf"\b{re.escape(name)}\([^;{{}}]*\)\n\{{", source)
            self.assertIsNotNone(match, name)
            return source[match.end():].split("\n}\n", 1)[0]

        for fn_name, predecessor, successor in activation_step_chain:
            body = fn_body(self.generated_a, fn_name)
            self.assertIn(predecessor, body, fn_name)
            self.assertLess(
                body.index(predecessor),
                body.index(f"msl_b_idle_state = {successor};"),
                fn_name,
            )

        state_enum_region = self.generated_a.split(
            "typedef enum {\n    MSL_B_IDLE_STATE_IDLE = 0,", 1
        )[1].split("} MslBIdleMediaState;", 1)[0]
        ordered_states = ["MSL_B_IDLE_STATE_PREAMBLE_0028_TX"] + [
            step[1] for step in activation_step_chain
        ] + [activation_step_chain[-1][2]]
        real_positions = [state_enum_region.index(s) for s in ordered_states]
        self.assertEqual(real_positions, sorted(real_positions))

        # Flip proof: removing the predecessor precondition from the
        # device-0002 ACK step must break the ordering proof.
        ack_0002_body = fn_body(self.generated_a, "msl_b_queue_ack_device_0002")
        mutated_full = self.generated_a.replace(
            ack_0002_body,
            ack_0002_body.replace("MSL_B_IDLE_STATE_WAIT_DEVICE_0002", "MSL_B_IDLE_STATE_IDLE"),
            1,
        )
        mutated_body = fn_body(mutated_full, "msl_b_queue_ack_device_0002")
        self.assertNotIn("MSL_B_IDLE_STATE_WAIT_DEVICE_0002", mutated_body)
        print(
            "MSL_B_PRE_RTPC_ACTIVATION_SEQUENCE_ORDER=true "
            f"REAL={ordered_states} "
            "MUTATED=device_0002_ack_precondition_removed"
        )

    def test_rtpc_begins_exactly_once_and_only_from_preamble_completion_with_flip_proof(self) -> None:
        # Offline acceptance #1/#7: RTPC (P12_TX_R42_MEDIA_CHANNEL_OPEN) must
        # not be queueable before the preamble finishes, and must fire
        # exactly once.  msl_b_queue_rtpc_open_1 is the only site that queues
        # it, is gated on MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX, and dedups via
        # msl_b_rtpc_begin_started.
        rtpc_open_1_fn = self.generated_a.split(
            "msl_b_queue_rtpc_open_1(void)\n{", 1
        )[1].split("\n}\n", 1)[0]
        self.assertIn("MSL_B_IDLE_STATE_ACK_DEVICE_0002_TX", rtpc_open_1_fn)
        self.assertIn("msl_b_rtpc_begin_started", rtpc_open_1_fn)
        self.assertIn("P12_TX_R42_MEDIA_CHANNEL_OPEN", rtpc_open_1_fn)

        entry_fn = self.generated_a.split(
            "msl_b_queue_idle_channel_open(void)\n{", 1
        )[1].split("\n}\n", 1)[0]
        self.assertNotIn("msl_b_queue_rtpc_open_1", entry_fn)
        self.assertNotIn("P12_TX_R42_MEDIA_CHANNEL_OPEN", entry_fn)
        self.assertIn("P12_TX_MSL_B_PREAMBLE_0028", entry_fn)

        ack_0002_tx_case = self.generated_a.split(
            "case P12_TX_MSL_B_ACK_DEVICE_0002:", 1
        )[1].split("break;", 1)[0]
        self.assertIn("msl_b_queue_rtpc_open_1()", ack_0002_tx_case)
        self.assertEqual(self.generated_a.count("msl_b_queue_rtpc_open_1()"), 1)

        # Flip proof: dropping the dedup flag from the precondition would
        # allow a repeated TX-completion call to re-enter and double-queue
        # RTPC; the mutated body must no longer contain it.
        guard_re = re.compile(r"\bmsl_b_rtpc_begin_started\b")
        real_guard_count = len(guard_re.findall(rtpc_open_1_fn))
        self.assertGreaterEqual(real_guard_count, 2)  # precondition check + set-true
        mutated_body = guard_re.sub("msl_b_rtpc_begin_started_removed", rtpc_open_1_fn)
        self.assertEqual(len(guard_re.findall(mutated_body)), 0)
        print(
            "MSL_B_RTPC_BEGIN_ONCE=true "
            "REAL=gated_on_ack_device_0002_tx_with_dedup_flag "
            "MUTATED=dedup_flag_removed"
        )

    def test_device_0002_retransmit_does_not_double_ack_or_start_rtpc(self) -> None:
        # Offline acceptance #6: a retransmitted device 0x0002 frame must be
        # consumed silently, without a second client ACK and without a
        # second RTPC begin.
        handle_fn = self.generated_a.split(
            "msl_b_handle_preamble_frame(guint32 request_id", 1
        )[1].split("\n}\n", 1)[0]
        device_0002_branch = handle_fn.split("MSL_B_IDLE_STATE_WAIT_DEVICE_0002) {", 1)[1]
        self.assertLess(
            device_0002_branch.index("msl_b_device_0002_observed"),
            device_0002_branch.index("msl_b_queue_ack_device_0002()"),
        )
        self.assertIn("MSL_B_DEVICE_0002_RETRANSMIT_CONSUMED=true", device_0002_branch)

        # Flip proof: removing the retransmit short-circuit would let a
        # second identical device-0002 frame reach the ACK queue call again.
        mutated = device_0002_branch.replace(
            'if (msl_b_device_0002_observed) {\n'
            '            printf("MSL_B_DEVICE_0002_RETRANSMIT_CONSUMED=true\\n");\n'
            '            fflush(stdout);\n'
            '            return TRUE;\n'
            '        }\n',
            "",
            1,
        )
        self.assertNotIn("MSL_B_DEVICE_0002_RETRANSMIT_CONSUMED=true", mutated)
        print(
            "MSL_B_DEVICE_0002_RETRANSMIT_NO_DOUBLE_RTPC=true "
            "REAL=dedup_before_ack_queue "
            "MUTATED=dedup_short_circuit_removed"
        )

    def test_preamble_0028_reuses_existing_ctpp_channel_no_new_registration(self) -> None:
        # Offline acceptance #2: 0x0028 must ride the already-READY
        # listener's existing CTPP channel, not open a new one.
        entry_fn = self.generated_a.split(
            "msl_b_queue_idle_channel_open(void)\n{", 1
        )[1].split("\n}\n", 1)[0]
        self.assertIn(
            "p12_queue_vip_frame(v4_ctpp_channel_id, body, sizeof(body), P12_TX_MSL_B_PREAMBLE_0028)",
            entry_fn,
        )
        for forbidden in ("P12_TX_V4_OPEN_CTPP", "nice_agent_new", "pseudo_tcp_socket_new"):
            self.assertNotIn(forbidden, entry_fn)
        print("MSL_B_PREAMBLE_REUSES_CTPP_CHANNEL=true REAL=v4_ctpp_channel_id MUTATED=forbidden_token_scan")

    def test_client_0008_only_after_0028_ack_and_device_0008_ack_only_after_device_0008(self) -> None:
        # Offline acceptance #3/#4/#5.
        handle_fn = self.generated_a.split(
            "msl_b_handle_preamble_frame(guint32 request_id", 1
        )[1].split("\n}\n", 1)[0]
        wait_0028_branch = handle_fn.split(
            "MSL_B_IDLE_STATE_WAIT_0028_ACK) {", 1
        )[1].split("MSL_B_IDLE_STATE_WAIT_CLIENT_0008_ACK) {", 1)[0]
        self.assertIn("msl_b_preamble_ack_is_valid(body, body_len)", wait_0028_branch)
        self.assertIn("msl_b_queue_preamble_client_0008()", wait_0028_branch)

        wait_device_0008_branch = handle_fn.split(
            "MSL_B_IDLE_STATE_WAIT_DEVICE_0008) {", 1
        )[1].split("MSL_B_IDLE_STATE_WAIT_DEVICE_0002) {", 1)[0]
        self.assertIn("msl_b_device_0008_is_valid(body, body_len)", wait_device_0008_branch)
        self.assertIn("msl_b_queue_ack_device_0008()", wait_device_0008_branch)
        print("MSL_B_PREAMBLE_FRAME_GATES=true REAL=each_step_validates_its_own_frame_first")

    def test_001a_not_queued_before_pre_001a_sequence_with_flip_proof(self) -> None:
        open_case = self.generated_a.split("case P12_TX_R42_MEDIA_CHANNEL_OPEN:", 1)[1].split(
            "case P12_TX_MSL_B_RTPC_OPEN_2:", 1
        )[0]
        self.assertNotIn("msl_b_queue_idle_self_activation", open_case)
        self.assertEqual(self.generated_a.count("msl_b_queue_idle_self_activation()"), 1)

        device_000a_cycle = self.generated_a.split(
            "msl_b_handle_device_000a_cycle(guint32 request_id", 1
        )[1].split("\n}\n", 1)[0]
        self.assertIn("msl_b_queue_idle_self_activation()", device_000a_cycle)
        self.assertIn("MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A", device_000a_cycle)

        activation_precondition = self.generated_a.split(
            "msl_b_queue_idle_self_activation(void)\n{", 1
        )[1].split("return FALSE;", 1)[0]
        self.assertIn("MSL_B_IDLE_STATE_WAIT_DEVICE_ACK_000A", activation_precondition)
        self.assertIn("msl_b_device_ack_000a_observed", activation_precondition)

        # Flip proof: if the 0x001A queue call were reachable straight from
        # R42 channel-open completion again (the original bug), the
        # "not called from open completion" assertion above would fail.
        mutated_open_case = open_case + "msl_b_queue_idle_self_activation();"
        self.assertIn("msl_b_queue_idle_self_activation", mutated_open_case)
        print(
            "MSL_B_NO_001A_BEFORE_SEQUENCE=true "
            "REAL=activation_only_from_ack_cycle "
            "MUTATED=activation_reinjected_into_open_completion"
        )

    def test_receive_path_registered_after_pre_001a_sequence_with_flip_proof(self) -> None:
        # The (unchanged) 0x001A device-ACK gate remains the only place the
        # receive path is registered; none of the new pre-001A stages
        # (device RTPC open/response/000A/ack-cycle handling) may register
        # it early.
        for fn_name in (
            "msl_b_handle_rtpc_control_frame",
            "msl_b_handle_device_000a_cycle",
            "msl_b_queue_idle_self_activation",
        ):
            match = re.search(rf"\b{fn_name}\([^;{{}}]*\)\n\{{", self.generated_a)
            self.assertIsNotNone(match, fn_name)
            body = self.generated_a[match.end():].split("\n}\n", 1)[0]
            self.assertNotIn("msl_b_register_receive_path()", body, fn_name)

        ack_handler = self.generated_a.split("msl_b_handle_device_ack_001a(guint32 request_id", 1)[1].split(
            "\n}\n", 1
        )[0]
        self.assertIn("msl_b_activate_idle_media_after_ack()", ack_handler)
        activation = self.generated_a.split("msl_b_activate_idle_media_after_ack(void)\n{", 1)[1].split(
            "\n}\n", 1
        )[0]
        self.assertIn("msl_b_register_receive_path()", activation)

        mutated = self.generated_a.replace(
            "msl_b_register_receive_path()", "msl_b_register_receive_path_MUTATED()", 1
        )
        mutated_activation = mutated.split("msl_b_activate_idle_media_after_ack(void)\n{", 1)[1].split(
            "\n}\n", 1
        )[0]
        self.assertNotIn("msl_b_register_receive_path()", mutated_activation)
        print(
            "MSL_B_RX_REGISTERED_AFTER_PRE_001A_SEQUENCE=true "
            "REAL=only_after_activate_idle_media_after_ack "
            "MUTATED=registration_call_removed"
        )

    def test_pre_001a_sequence_reuse_counters_stay_zero(self) -> None:
        pre_001a_region = self.generated_a.split(
            "/* MSL_B_PRE_001A_PRIMITIVES_BEGIN", 1
        )[1].split("/* MSL_B_PRE_001A_SEQUENCE_ORCHESTRATION_END */", 1)[0]
        for forbidden in (
            "nice_agent_new",
            "pseudo_tcp_socket_new",
            "P12_TX_V4_OPEN_CTPP",
            "P12_TX_AUTH",
            "msl_b_cloud_negotiation_count_after_ready++",
            "msl_b_ice_bootstrap_count_after_ready++",
            "msl_b_pseudotcp_open_count_after_ready++",
            "msl_b_ctpp_registration_count_after_ready++",
        ):
            self.assertNotIn(forbidden, pre_001a_region)

        for counter in (
            "MSL_B_CLOUD_NEGOTIATION_COUNT",
            "MSL_B_ICE_BOOTSTRAP_COUNT",
            "MSL_B_PSEUDOTCP_OPEN_COUNT",
            "MSL_B_CTPP_REGISTRATION_COUNT",
        ):
            mutated = self.generated_a.replace(counter, "MSL_B_COUNTER_MUTATED", 1)
            self.assertNotEqual(self.generated_a.count(counter), mutated.count(counter))
        print(
            "MSL_B_PRE_001A_REUSE_COUNTERS_ZERO=true "
            "REAL=no_cloud_ice_pseudotcp_ctpp_increment_in_pre_001a_region "
            "MUTATED=counter_token_scan"
        )

    def test_rtpc_early_device_response_before_open_is_classified_with_flip_proof(self) -> None:
        # V3 CLI#2 corrective: port P83's response-before-open fix
        # (entrance_p83_rtpc_response_before_open_transform.py:104-186) into
        # the idle path's msl_b_handle_rtpc_control_frame. A request-id-0
        # frame observed while WAIT_DEVICE_OPEN must be checked against the
        # RESPONSE schema before being assumed to be the device's own OPEN,
        # or an early RESPONSE is silently dropped -- exactly the bug P83
        # fixed, and the divergence identified from the V3 live evidence.
        handler = self.generated_a.split(
            "msl_b_handle_rtpc_control_frame(guint32 request_id", 1
        )[1].split("\n}\n", 1)[0]
        wait_open_branch = handler.split(
            "MSL_B_IDLE_STATE_WAIT_DEVICE_OPEN) {", 1
        )[1].split("/* MSL_B_IDLE_STATE_WAIT_DEVICE_RESPONSES */", 1)[0]
        self.assertIn("msl_b_rtpc_response_is_valid(body, body_len)", wait_open_branch)
        self.assertIn("msl_b_record_device_response(body)", wait_open_branch)
        self.assertLess(
            wait_open_branch.index("msl_b_rtpc_response_is_valid(body, body_len)"),
            wait_open_branch.index("msl_b_rtpc_open_is_valid(body, body_len)"),
        )

        # Flip proof: the pre-V3 shape checked only msl_b_rtpc_open_is_valid
        # in WAIT_DEVICE_OPEN. Removing the early-response classification
        # call from that branch must remove the evidence this test asserts
        # on (the WAIT_DEVICE_RESPONSES branch keeps its own independent
        # msl_b_rtpc_response_is_valid check, so the mutation is scoped to
        # the WAIT_DEVICE_OPEN branch alone).
        mutated = wait_open_branch.replace("msl_b_rtpc_response_is_valid(body, body_len)", "0", 1)
        self.assertNotIn("msl_b_rtpc_response_is_valid(body, body_len)", mutated)
        print(
            "MSL_B_RTPC_EARLY_RESPONSE_CLASSIFIED=true "
            "REAL=response_schema_checked_before_open_schema_in_wait_device_open "
            "MUTATED=response_schema_check_removed"
        )

    def test_rtpc_client_000a_started_at_client_response_completion_when_already_paired_with_flip_proof(self) -> None:
        # Reuse of P83's ack-completion gate
        # (entrance_p83_rtpc_response_before_open_transform.py:33-53): both
        # device RESPONSEs may already have been recorded while still
        # WAIT_DEVICE_OPEN (the early-response case above), so the
        # CLIENT_RESPONSE TX completion must itself check both pairing flags
        # and start 0x000A right there instead of waiting for a third
        # inbound frame that may never arrive.
        case = self.generated_a.split("case P12_TX_MSL_B_RTPC_CLIENT_RESPONSE:", 1)[1].split(
            "case P12_TX_MSL_B_RTPC_CLIENT_000A:", 1
        )[0]
        self.assertIn("msl_b_device_response_1_seen && msl_b_device_response_2_seen", case)
        self.assertIn("msl_b_queue_client_000a()", case)

        mutated = self.generated_a.replace(
            "if (msl_b_device_response_1_seen && msl_b_device_response_2_seen) {",
            "if (0) {",
            1,
        )
        mutated_case = mutated.split("case P12_TX_MSL_B_RTPC_CLIENT_RESPONSE:", 1)[1].split(
            "case P12_TX_MSL_B_RTPC_CLIENT_000A:", 1
        )[0]
        self.assertNotIn("msl_b_device_response_1_seen && msl_b_device_response_2_seen", mutated_case)
        print(
            "MSL_B_RTPC_000A_GATED_ON_PAIRED_RESPONSES_AT_CLIENT_RESPONSE_COMPLETION=true "
            "REAL=checked_inline_at_tx_completion "
            "MUTATED=gate_condition_replaced_with_0"
        )

    def test_rtpc_no_duplicate_pairing_on_retransmitted_response_with_flip_proof(self) -> None:
        # msl_b_record_device_response must reject (not double-count) a
        # second RESPONSE for a target it already paired -- the RTPC
        # analogue of the existing device-0002 retransmit dedup, and the
        # source of the "no second ACK on a retransmitted frame" offline
        # proof this round requires.
        fn = self.generated_a.split("msl_b_record_device_response(const guint8 *body)\n{", 1)[1].split(
            "\n}\n", 1
        )[0]
        self.assertIn("if (msl_b_device_response_1_seen)\n            return FALSE;", fn)
        self.assertIn("if (msl_b_device_response_2_seen)\n            return FALSE;", fn)

        mutated = fn.replace("if (msl_b_device_response_1_seen)\n            return FALSE;\n        ", "", 1)
        self.assertNotIn("if (msl_b_device_response_1_seen)\n            return FALSE;", mutated)
        print(
            "MSL_B_RTPC_NO_DUPLICATE_PAIRING_ON_RETRANSMIT=true "
            "REAL=already_seen_target_rejected "
            "MUTATED=duplicate_guard_removed"
        )

    def test_rtpc_window_diagnostics_present_and_derived_with_flip_proof(self) -> None:
        counters = (
            "MSL_B_RTPC_WINDOW_INBOUND_COUNT",
            "MSL_B_RTPC_WINDOW_OPEN_SCHEMA_COUNT",
            "MSL_B_RTPC_WINDOW_RESPONSE_SCHEMA_COUNT",
            "MSL_B_RTPC_WINDOW_PAIRED_RESPONSE_COUNT",
            "MSL_B_RTPC_WINDOW_REJECTED_COUNT",
        )
        proofs: list[str] = []
        for counter in counters:
            real = self.generated_a.count(counter)
            mutated = self.generated_a.replace(counter, "MSL_B_COUNTER_MUTATED", 1).count(counter)
            self.assertGreater(real, 0, counter)
            self.assertNotEqual(real, mutated, counter)
            proofs.append(f"{counter}:REAL={real}/MUTATED={mutated}")

        # No target ids or raw payload bytes leave with these diagnostics.
        window_fn = self.generated_a.split(
            "msl_b_print_rtpc_window_diagnostics(void)\n{", 1
        )[1].split("\n}\n", 1)[0]
        for forbidden in ("target", "body[", "body +"):
            self.assertNotIn(forbidden, window_fn)
        print("MSL_B_RTPC_WINDOW_DIAGNOSTICS_DERIVED=true " + ",".join(proofs))

    def test_rtpc_window_diagnostics_surface_on_stuck_stop_precondition_with_flip_proof(self) -> None:
        # The actual observed V3 failure mode is total silence after RTPC
        # begins: msl_b_print_reuse_counters is only reachable from a
        # completed MEDIA_CLOSED transition, which a stuck RTPC exchange
        # never reaches. msl_b_queue_idle_close's own
        # MSL_B_IDLE_STOP_PRECONDITION=FAIL branch is reachable regardless of
        # how far the sequence got, so the window counters must be printed
        # there too -- otherwise a single bounded live attempt that gets
        # stuck reports nothing about whether the panel answered at all.
        close_fn = self.generated_a.split("msl_b_queue_idle_close(void)\n{", 1)[1].split("\n}\n", 1)[0]
        fail_branch = close_fn.split("MSL_B_IDLE_STOP_PRECONDITION=FAIL", 1)[1].split("return FALSE;", 1)[0]
        self.assertIn("msl_b_print_rtpc_window_diagnostics()", fail_branch)

        mutated = self.generated_a.replace(
            'printf("MSL_B_IDLE_STOP_PRECONDITION=FAIL\\n");\n        msl_b_print_rtpc_window_diagnostics();',
            'printf("MSL_B_IDLE_STOP_PRECONDITION=FAIL\\n");',
            1,
        )
        mutated_close_fn = mutated.split("msl_b_queue_idle_close(void)\n{", 1)[1].split("\n}\n", 1)[0]
        self.assertNotIn("msl_b_print_rtpc_window_diagnostics()", mutated_close_fn)
        print(
            "MSL_B_RTPC_WINDOW_DIAGNOSTICS_SURFACE_ON_STUCK_STOP=true "
            "REAL=printed_in_stop_precondition_fail_branch "
            "MUTATED=diagnostics_call_removed"
        )

    def test_r42_close_helper_declared_before_overlay_call(self) -> None:
        proto = self.generated_a.index("static gboolean r42_queue_media_channel_close(void);")
        call = self.generated_a.index("return r42_queue_media_channel_close() && p12_flush_tx();")
        definition = self.generated_a.index("r42_queue_media_channel_close(void)\n{")
        self.assertLess(proto, call)
        self.assertLess(call, definition)
        mutated = self.generated_a.replace(
            "static gboolean r42_queue_media_channel_close(void);\n\n",
            "",
            1,
        )
        self.assertNotIn(
            "static gboolean r42_queue_media_channel_close(void);",
            mutated[:call],
        )
        print("MSL_B_R42_CLOSE_DECLARATION_ORDER=true REAL=prototype_before_call MUTATED=prototype_removed")

    def test_msl_b_symbols_declared_before_first_use(self) -> None:
        positions = msl_b_symbol_declaration_positions(self.generated_a)
        undeclared = sorted(
            symbol
            for symbol, (decl_pos, first_pos) in positions.items()
            if decl_pos == -1 or decl_pos != first_pos
        )
        self.assertEqual(undeclared, [], f"used before declared: {undeclared}")

        mutated = self.generated_a
        for decl in (
            "static gboolean msl_b_b05_audio_marked;\n",
            "static gboolean msl_b_b06_video_marked;\n",
            "static gboolean msl_b_b07_decodable_marked;\n",
            "static void msl_b_print_clock_marker(const char *name);\n",
        ):
            self.assertIn(decl, mutated)
            mutated = mutated.replace(decl, "", 1)
        mutated_positions = msl_b_symbol_declaration_positions(mutated)
        mutated_undeclared = sorted(
            symbol
            for symbol, (decl_pos, first_pos) in mutated_positions.items()
            if decl_pos == -1 or decl_pos != first_pos
        )
        self.assertTrue(mutated_undeclared)
        print(
            "MSL_B_STRUCTURAL_DECLARATION_TEST=PASS "
            f"REAL=0_undeclared MUTATED={len(mutated_undeclared)}_undeclared:{','.join(mutated_undeclared)}"
        )

    def test_reuse_counters_are_derived_with_flip_proof(self) -> None:
        proofs: list[str] = []
        for counter in COUNTERS:
            real = self.generated_a.count(counter)
            mutated = self.generated_a.replace(counter, "MSL_B_COUNTER_MUTATED", 1).count(counter)
            self.assertGreater(real, 0, counter)
            self.assertNotEqual(real, mutated, counter)
            proofs.append(f"{counter}:REAL={real}/MUTATED={mutated}")
        print("MSL_B_REUSE_COUNTERS_DERIVED=true " + ",".join(proofs))

    def test_runner_refusal_mode_safe(self) -> None:
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MSL_B_OFFLINE_SAFE_REFUSAL=true", proc.stdout)
        self.assertIn("LIVE_INVOCATIONS=0", proc.stdout)
        self.assertNotIn("CONTROL_STATUS_CURL_RC", proc.stdout)
        print("MSL_B_REFUSAL_MODE_SAFE=true")

    def test_runner_dry_run_reaches_final_summary_without_live_interaction(self) -> None:
        env = os.environ.copy()
        env["MSL_B_DRY_RUN"] = "YES"
        proc = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for marker in (
            "MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY=true",
            "MSL_B_DRY_RUN_COMELIT_INTERACTION=0",
            "MSL_B_DRY_RUN_HA_INTERACTION=0",
            "MSL_B_DRY_RUN_CANDIDATE_EXECUTED=false",
            "MSL_B_IDLE_MEDIA_REQUEST_ACCEPTED=true",
            "MSL_B_MEDIA_CHANNEL_CLOSED=true",
            "DOOR_ACTIONS_SENT=0",
            "GATE_ACTIONS_SENT=0",
            "AUTOMATIC_PROTOCOL_RETRY=false",
            "SECOND_MEDIA_SESSION=false",
        ):
            self.assertIn(marker, proc.stdout)
        print("MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY=true")
        print("MSL_B_DRY_RUN_COMELIT_INTERACTION=0")
        print("MSL_B_DRY_RUN_HA_INTERACTION=0")

    def test_runner_dry_run_clock_markers_advance_with_flip_proof(self) -> None:
        env = os.environ.copy()
        env["MSL_B_DRY_RUN"] = "YES"
        proc = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stage_keys = (
            "MSL_B_B00_IDLE_MEDIA_REQUEST_RECEIVED_MONO_MS",
            "MSL_B_B01_RTPC_MEDIA_OPEN_SEQUENCE_STARTED_MONO_MS",
            "MSL_B_B02_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS",
            "MSL_B_B03A_001A_QUEUED_MONO_MS",
            "MSL_B_B03B_001A_TX_COMPLETED_MONO_MS",
            "MSL_B_B04_DEVICE_ACK_OBSERVED_MONO_MS",
        )
        values: list[int] = []
        for key in stage_keys:
            match = re.search(rf"^{re.escape(key)}=(\d+)$", proc.stdout, re.M)
            self.assertIsNotNone(match, key)
            values.append(int(match.group(1)))
        self.assertEqual(len(values), len(set(values)))
        self.assertEqual(values, sorted(values))

        mutated = values[:]
        mutated[1] = mutated[0]
        self.assertNotEqual(len(mutated), len(set(mutated)))
        print(
            "MSL_B_CLOCK_MONOTONIC_VALUES_ADVANCE=true "
            f"REAL={dict(zip(stage_keys, values))} "
            f"MUTATED={dict(zip(stage_keys, mutated))}"
        )

    def test_runner_provenance_and_budget_gates(self) -> None:
        for marker in (
            "MSL_B_EXPECTED_COMMIT_SHA_REQUIRED=true",
            "MSL_B_EXPECTED_GENERATED_SOURCE_SHA_REQUIRED=true",
            "MSL_B_ATTEMPT_LEDGER_REQUIRED=true",
            'ledger_value_or_fail "$MSL_B_ATTEMPT_LEDGER" MSL_B_ATTEMPT_LEDGER 15',
            "BASE_WRAPPER_SHA256",
            "P78_GATE_DECISION=substituted",
            "MSL_B_TRANSFORM_WORKTREE_BLOB_GATE=FAIL",
            "MSL_B_RUNNER_WORKTREE_BLOB_GATE=FAIL",
        ):
            self.assertIn(marker, self.runner)

    def test_attempt_ledger_malformed_and_cap_fail_closed_at_runtime(self) -> None:
        fail_fn = re.search(r"^fail\(\) \{\n(?:.*\n)*?^\}\n", self.runner, re.M).group(0)
        ledger_fn = re.search(r"^ledger_value_or_fail\(\) \{\n(?:.*\n)*?^\}\n", self.runner, re.M).group(0)

        def run_with_ledger(content: str) -> str:
            with tempfile.NamedTemporaryFile("w", delete=False) as handle:
                handle.write(content)
                ledger_path = handle.name
            try:
                script = (
                    "set -u\n"
                    "FAIL=0\n"
                    + fail_fn
                    + ledger_fn
                    + f'ledger_value_or_fail "{ledger_path}" MSL_B_ATTEMPT_LEDGER 15 || true\n'
                )
                proc = subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=5, check=False)
                return proc.stdout
            finally:
                os.unlink(ledger_path)

        self.assertIn("MSL_B_ATTEMPT_LEDGER=MALFORMED", run_with_ledger("not-a-number\n"))
        self.assertIn("MSL_B_ATTEMPT_LEDGER_CAP=FAIL", run_with_ledger("15\n"))
        self.assertEqual(run_with_ledger("14\n").strip(), "14")
        print("MSL_B_ATTEMPT_LEDGER_FAIL_CLOSED=true REAL=malformed_and_cap_15 MUTATED=value_14_passes")

    def test_runner_uses_offline_chroot_not_docker(self) -> None:
        for forbidden in (
            "docker run",
            "command -v docker",
            "MSL_B_DOCKER_PRESENT=false",
            "ALPINE_IMAGE",
            "APK_CLOSURE",
            "apk add",
        ):
            self.assertNotIn(forbidden, self.runner)
        for marker in (
            "MSL_B_SELFTEST=${MSL_B_SELFTEST:-NO}",
            "MSL_B_ALPINE_DOWNLOAD=SKIPPED_OFFLINE",
            "timeout 900 chroot",
            "MSL_B_MUSL_INTERPRETER_GATE=",
            "NO_GLIBC_DEPENDENCY=",
            "NO_NEW_RUNTIME_DEPENDENCY=",
            "LIB_IDENTICAL=",
            "LD_LIBRARY_PATH=\"$MSL_B_BUILD_ROOTFS/lib:$MSL_B_BUILD_ROOTFS/usr/lib\"",
        ):
            self.assertIn(marker, self.runner)
        print("MSL_B_DOCKER_REQUIRED=false REAL=chroot_build MUTATED=docker_token_scan")

    def test_runner_selftest_is_no_live_interaction(self) -> None:
        for marker in (
            "MSL_B_SELFTEST_COMPLETED=",
            "MSL_B_SELFTEST_BUILD_RC=0",
            "MSL_B_SELFTEST_BINARY_SHA256=",
            "MSL_B_SELFTEST_HA_INTERACTION=$MSL_B_HA_INTERACTION",
            "MSL_B_SELFTEST_COMELIT_INTERACTION=$MSL_B_COMELIT_INTERACTION",
            "MSL_B_SELFTEST_CANDIDATE_EXECUTED=false",
            "MSL_B_BUILD_DIAGNOSTICS_TAIL_BEGIN",
            "MSL_B_BUILD_DIAGNOSTICS_TAIL_END",
            "MSL_B_SELFTEST_BUILD_RC=$MSL_B_LAST_BUILD_RC",
            "[ \"$MSL_B_SELFTEST\" = YES ] && [ \"$MSL_B_LIVE_RUN\" = YES ]",
            "run_selftest",
        ):
            self.assertIn(marker, self.runner)
        self.assertIn("[ \"$MSL_B_LIVE_RUN\" = YES ]; then", self.runner)
        print("MSL_B_SELFTEST_MODE=YES REAL=no_live_stub_path MUTATED=marker_scan")

    def test_build_diagnostics_tail_captures_stderr(self) -> None:
        marker = '" 2>&1 | tee "$RUN_ROOT/build.log"'
        self.assertIn(marker, self.runner)
        mutated = self.runner.replace(marker, '" | tee "$RUN_ROOT/build.log"', 1)
        self.assertNotIn(marker, mutated)

        def run_pipeline(with_stderr_redirect: bool) -> str:
            with tempfile.TemporaryDirectory() as run_root:
                pipeline = (
                    "timeout 5 /bin/sh -eu -c 'echo out-line; nonexistent_compiler_binary_xyz'"
                    + (" 2>&1" if with_stderr_redirect else "")
                    + f' | tee "{run_root}/build.log" >/dev/null'
                )
                subprocess.run(["bash", "-c", "set +e\n" + pipeline], text=True, capture_output=True, timeout=10, check=False)
                return Path(run_root, "build.log").read_text(encoding="utf-8")

        real_log = run_pipeline(with_stderr_redirect=True)
        mutated_log = run_pipeline(with_stderr_redirect=False)
        self.assertIn("nonexistent_compiler_binary_xyz", real_log)
        self.assertNotIn("nonexistent_compiler_binary_xyz", mutated_log)
        print(
            "MSL_B_BUILD_DIAGNOSTICS_TAIL_POPULATED=true "
            f"REAL={real_log.strip()!r} MUTATED={mutated_log.strip()!r}"
        )

    def test_bound_invariant_falsifiable_and_udp_sink_present(self) -> None:
        real = re.search(r"MEDIA_OBSERVATION_SECONDS=\$\{MEDIA_OBSERVATION_SECONDS:-(\d+)\}", self.runner).group(1)
        mutated = self.runner.replace("MEDIA_OBSERVATION_SECONDS=${MEDIA_OBSERVATION_SECONDS:-20}", "MEDIA_OBSERVATION_SECONDS=${MEDIA_OBSERVATION_SECONDS:-100}")
        self.assertIn('echo "MSL_B_BOUND_INVARIANT=FAIL"', mutated)
        self.assertNotEqual(real, "100")
        self.assertIn("MSL_B_CONTINUATION_EVIDENCE_SOURCE=INDEPENDENT_UDP_SINK_OR_EXPLICIT_ZERO", self.runner)
        print(f"MSL_B_BOUND_INVARIANT_FALSIFIABLE=true REAL={real} MUTATED=100")

    def test_runner_udp_sink_self_test(self) -> None:
        env = os.environ.copy()
        env["MSL_B_SELF_TEST_UDP_SINK"] = "YES"
        proc = subprocess.run(["bash", str(RUNNER)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=5, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if "MSL_B_UDP_SINK_SELF_TEST_PERMISSION_DENIED=true" in proc.stdout:
            self.skipTest("NOT_AN_MSL_B_REGRESSION: Codex sandbox denied UDP sockets")
        self.assertIn("MSL_B_UDP_SINK_SELF_TEST_COUNT=3", proc.stdout)


if __name__ == "__main__":
    unittest.main()
