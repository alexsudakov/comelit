from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_p116_r29_listener_attached_media_live_transform.py"
RUNNER = MEDIA / "ct120_run_p116_r29_listener_attached_media_live.sh"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r29_listener_attached_media_live_transform as r29


def region(text: str, start: str, end: str) -> str:
    s = text.index(start)
    e = text.index(end, s)
    return text[s:e]


class P116R29BHelperLocalInboundMediaMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = r29.transform(SOURCE.read_text(encoding="utf-8"))
        cls.state_region = region(
            cls.generated,
            "R29_LISTENER_ATTACHED_MEDIA_STATE_BEGIN",
            "R29_LISTENER_ATTACHED_MEDIA_STATE_END",
        )
        cls.attached_region = region(
            cls.generated,
            "R29_ATTACHED_MEDIA_FUNCTIONS_BEGIN",
            "R29_ATTACHED_MEDIA_FUNCTIONS_END",
        )
        cls.call_init_region = region(
            cls.generated,
            "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
            "Persistent listener:",
        )
        cls.self_activation_region = region(
            cls.generated,
            "entrance_signal_queue_self_activation(void)\n{",
            "static gboolean\nentrance_signal_queue_video_event",
        )
        cls.client_001a_region = region(
            cls.generated,
            "p78_queue_rtpc_client_001a(void)\n{",
            "static gboolean\np78_begin_rtpc_control",
        )
        cls.selfcheck_region = region(
            cls.generated,
            "static int\nr29_selfcheck",
            "/* === R29_ATTACHED_MEDIA_FUNCTIONS_END === */",
        )
        cls.doc = (MEDIA / "P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md").read_text(
            encoding="utf-8"
        )
        cls.doc_single_line = " ".join(cls.doc.split())

    def test_open_model_remains_blocked_without_call_ctp_mapping(self) -> None:
        self.assertIn("R29_MEDIA_OPEN_MODEL=BLOCKED", self.attached_region)
        self.assertIn(
            "CALL_INIT_ON_REGISTERED_CTPP_NO_SEPARATE_CALL_CTP_OR_MEDIAREQ26_BUILDER",
            self.attached_region,
        )
        self.assertIn("INBOUND_CALL_CTP_CAPTURE_IMPLEMENTED=false", self.attached_region)
        self.assertIn("CALL_BOUND_MEDIAREQ26_USES_INBOUND_CTP=false", self.attached_region)
        self.assertIn("OPEN_FIELDS_HAVE_PROVEN_SOURCES=false", self.attached_region)

    def test_stop_model_remains_blocked_without_call_bound_stop_builder(self) -> None:
        self.assertIn("R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED", self.attached_region)
        self.assertIn(
            "NO_PROVEN_CALL_BOUND_MEDIAREQ26_STOP_BUILDER_OR_MEDIA_RX_POINTER_ID",
            self.attached_region,
        )
        self.assertIn("CALL_BOUND_MEDIAREQ26_STOP_GENERATION=BLOCKED", self.attached_region)
        self.assertIn("STOP_FIELDS_HAVE_PROVEN_SOURCES=false", self.attached_region)

    def test_001a_taxonomy_has_distinct_counters_and_forbidden_stubs(self) -> None:
        for marker in (
            "SELF_ACTIVATION_001A_SENT_COUNT=%u",
            "R27_REPEAT_001A_SENT_COUNT=%u",
            "CALL_BOUND_MEDIAREQ26_OPEN_SENT_COUNT=%u",
            "CALL_BOUND_MEDIAREQ26_STOP_SENT_COUNT=%u",
            "UNKNOWN_001A_FORM_BLOCKED_COUNT=%u",
        ):
            self.assertIn(marker, self.attached_region)
        self.assertNotIn("p12_queue_vip_frame", self.self_activation_region)
        self.assertNotIn("p12_queue_vip_frame", self.client_001a_region)
        self.assertNotIn("p78_queue_rtpc_client_001a();", self.generated)

    def test_registration_ctp_is_rejected_for_media(self) -> None:
        self.assertIn("r29_registration_ctp_rejected_for_media", self.state_region)
        self.assertIn("REGISTRATION_CTP_REJECTED_FOR_MEDIA=true", self.attached_region)
        self.assertNotIn("v4_ctpp_channel_id", self.attached_region)

    def test_call_init_hook_is_the_only_media_start_entry(self) -> None:
        self.assertIn("r29_start_attached_media_from_call_init(source)", self.call_init_region)
        self.assertEqual(
            self.generated.count("r29_start_attached_media_from_call_init(source)"),
            1,
        )
        self.assertIn("strcmp(source, V4_ENTRANCE) != 0", self.attached_region)

    def test_selfcheck_exercises_fail_closed_offline_path(self) -> None:
        ordered = (
            "r29_listener_registered_ready = TRUE;",
            "r29_registration_ctp_rejected_for_media();",
            "r29_unknown_001a_form_blocked();",
            "r29_start_attached_media_from_call_init(V4_ENTRANCE);",
            "r29_media_only_teardown(\"SELFCHECK\");",
            "NETWORK_WRITES_INTERCEPTED=true",
        )
        last = -1
        for needle in ordered:
            pos = self.selfcheck_region.index(needle)
            self.assertGreater(pos, last)
            last = pos
        self.assertIn("CALL_BOUND_MEDIAREQ26_OPEN_SENT_COUNT=%u", self.selfcheck_region)
        self.assertIn("CALL_BOUND_MEDIAREQ26_STOP_SENT_COUNT=%u", self.selfcheck_region)
        self.assertIn("MISSING_IMPLEMENTATION_EVIDENCE=", self.selfcheck_region)

    def test_round2_receive_path_settles_registered_ctpp_binding(self) -> None:
        for needle in (
            "Round 2 Receive Path Audit",
            "request_id == v4_ctpp_channel_id",
            "No peer-provided, call-scoped CTP binding is exposed",
            "architectural gap",
        ):
            self.assertIn(needle, self.doc)
        self.assertIn("single registered CTPP channel topology", self.doc_single_line)

    def test_round2_builder_and_media_rx_audits_remain_component_only(self) -> None:
        for needle in (
            "No 26-byte mediareq-shaped OPEN/STOP builder exists",
            "The RTPC/P80 state is a proven component analogue only",
        ):
            self.assertIn(needle, self.doc)
        self.assertIn(
            "the only media-request-like form is the 60-byte `0x001A`",
            self.doc_single_line,
        )
        self.assertIn(
            "not proof of native media RX pointer/id lifetime",
            self.doc_single_line,
        )

    def test_selfcheck_region_has_no_network_writes(self) -> None:
        for needle in ("send(", "sendto(", "connect(", "p12_queue_vip_frame"):
            self.assertNotIn(needle, self.selfcheck_region)

    def test_runtime_order_observation_markers_remain_bounded_unknown(self) -> None:
        for marker in (
            "MEDIA_CHANNEL_OPEN_REQUEST_SENT=%s",
            "MEDIA_CHANNEL_OPEN_RESPONSE_OBSERVED=%s",
            "CALL_BOUND_MEDIAREQ26_OPEN_SENT=%s",
            "VIDEO_RTP_STARTED=%s",
            "FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=%s",
        ):
            self.assertIn(marker, self.attached_region)
        self.assertIn('return "UNKNOWN";', self.attached_region)
        self.assertNotIn('return "BEFORE";', self.attached_region)
        self.assertNotIn('return "AFTER";', self.attached_region)

    def test_runner_forbids_live_before_handoff(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        forbidden_pos = text.index("LIVE_AUTHORIZED_FOR_THIS_TASK=false")
        live_refuse_pos = text.index("R29_LIVE_PREFLIGHT_REFUSED=LIVE_FORBIDDEN_FOR_R29B")
        status_pos = text.index('STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"')
        stop_pos = text.index('post_control stop "$STOP_RESPONSE"')
        self.assertLess(forbidden_pos, live_refuse_pos)
        self.assertLess(live_refuse_pos, status_pos)
        self.assertLess(status_pos, stop_pos)

    def test_parse_gates(self) -> None:
        subprocess.run([sys.executable, "-m", "py_compile", str(TRANSFORM)], cwd=REPO, check=True)
        subprocess.run(["bash", "-n", str(RUNNER)], cwd=REPO, check=True)


if __name__ == "__main__":
    unittest.main()
