"""Tests for COMELIT-P116-R42B-CANARY-OBSERVABILITY-001.

Covers the bounded ``media_diagnostics`` status contract added on top of the
frozen R42-b Door-preserving persistent-listener runtime:

1. status payload exposes all 16 ``media_diagnostics.*`` fields with the
   right shape;
2. reset/arm on a new call generation - stale-generation evidence never
   reads as current (negative case);
3. ``channel_source=RUNTIME_CALL_BOUND`` only once a runtime allocation is
   observed; never populated by a literal without one (negative case);
4. sanitizer redacts/drops unsafe values instead of crashing, and no raw
   bytes/secrets ever reach the payload (negative scan);
5. frozen Door/listener/SIGUSR2 contracts stay intact;
6. capture-literal gates (source) stay PASS, including in the new markers.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RUNTIME = REPO / "custom_components" / "comelit" / "runtime.py"
MEDIA_DIAGNOSTICS = REPO / "custom_components" / "comelit" / "media_diagnostics.py"
RING_MEDIA = REPO / "custom_components" / "comelit" / "ring_media.py"
MEDIA = ROOT / "research" / "media" / "v1"
DOOR_SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
BUILDER = MEDIA / "ct122_build_p116_r42_attached_media_candidate.sh"

sys.path.insert(0, str(MEDIA))
import entrance_p116_r42b_listener_attached_media_transform as r42b  # noqa: E402


def _load_media_diagnostics_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "comelit_media_diagnostics_canary", MEDIA_DIAGNOSTICS
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MD = _load_media_diagnostics_module()
MediaCallDiagnostics = MD.MediaCallDiagnostics
MEDIA_DIAGNOSTICS_FIELDS = MD.MEDIA_DIAGNOSTICS_FIELDS
CAPABILITIES_TRIGGER_FIELDS = MD.CAPABILITIES_TRIGGER_FIELDS
ALL_DIAGNOSTICS_FIELDS = MEDIA_DIAGNOSTICS_FIELDS + CAPABILITIES_TRIGGER_FIELDS


def _load_runtime_module() -> types.ModuleType:
    for name in (
        "aiohttp",
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.core",
        "custom_components",
        "custom_components.comelit",
        "custom_components.comelit.cloud",
        "custom_components.comelit.oauth",
        "custom_components.comelit.ring_media",
        "custom_components.comelit.sdp",
    ):
        sys.modules.pop(name, None)

    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(REPO / "custom_components")]
    comelit = types.ModuleType("custom_components.comelit")
    comelit.__path__ = [str(REPO / "custom_components" / "comelit")]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.comelit"] = comelit

    cloud = types.ModuleType("custom_components.comelit.cloud")
    cloud.ComelitCloudError = RuntimeError
    cloud.ComelitCloudHttpError = type(
        "ComelitCloudHttpError",
        (RuntimeError,),
        {"__init__": lambda self, status: setattr(self, "status", status)},
    )

    async def async_negotiate_p2p(*args: object, **kwargs: object) -> str:
        return ""

    cloud.async_negotiate_p2p = async_negotiate_p2p
    sys.modules["custom_components.comelit.cloud"] = cloud

    oauth = types.ModuleType("custom_components.comelit.oauth")
    oauth.ComelitOAuthError = RuntimeError
    oauth.ComelitOAuthManager = object
    sys.modules["custom_components.comelit.oauth"] = oauth

    ring_media = types.ModuleType("custom_components.comelit.ring_media")
    ring_media.RingMediaCoordinator = object
    sys.modules["custom_components.comelit.ring_media"] = ring_media

    sdp = types.ModuleType("custom_components.comelit.sdp")
    sdp.ComelitSdpError = RuntimeError
    sdp.transform_offer = lambda raw: raw
    sys.modules["custom_components.comelit.sdp"] = sdp

    sys.modules.pop("custom_components.comelit.runtime", None)
    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.runtime",
        RUNTIME,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeEvent:
    def __init__(self) -> None:
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True

    def clear(self) -> None:
        self._set = False


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode() for line in lines]

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _FakeStdout(lines)


def _status_ready_runtime_instance(module: types.ModuleType) -> object:
    """Build a ComelitRingRuntime with just enough state for .status()/_async_read_output()."""
    runtime = module.ComelitRingRuntime.__new__(module.ComelitRingRuntime)
    runtime._task = None
    runtime._listener_ready = _FakeEvent()
    runtime._attached_media_busy = _FakeEvent()
    runtime._attached_media_open = _FakeEvent()
    runtime._attached_media_closed = _FakeEvent()
    runtime._last_ring_event = None
    runtime._last_error = None
    runtime._last_native_exit_code = None
    runtime._last_native_failure_markers = []
    runtime._last_door_result = None
    runtime._door_diagnostic = {}
    runtime._door_result_future = None
    runtime._ring_media = None
    runtime._native_marker_tail = []
    runtime._ring_lines = []
    runtime._media_diagnostics = module.MediaCallDiagnostics()
    return runtime


async def _feed_lines(runtime: object, lines: list[str]) -> None:
    await runtime._async_read_output(_FakeProcess(lines))


class MediaCallDiagnosticsUnitTests(unittest.TestCase):
    """Direct tests of the bounded per-call-generation tracker."""

    def test_snapshot_has_exactly_the_sixteen_required_fields_before_any_call(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        snapshot = diag.snapshot()
        # The original 16-field contract (COMELIT-P116-R42B-CANARY-
        # OBSERVABILITY-001 round 1) must still be exactly 16 fields, all
        # present, unrenamed.
        self.assertEqual(len(MEDIA_DIAGNOSTICS_FIELDS), 16)
        self.assertTrue(set(MEDIA_DIAGNOSTICS_FIELDS).issubset(snapshot))
        # Round 2 (failure forensic) adds 7 more fields, additively.
        self.assertEqual(len(CAPABILITIES_TRIGGER_FIELDS), 7)
        self.assertEqual(set(snapshot), set(ALL_DIAGNOSTICS_FIELDS))
        self.assertEqual(len(ALL_DIAGNOSTICS_FIELDS), 23)
        self.assertIsNone(snapshot["call_generation"])
        self.assertIsNone(snapshot["media_channel"])
        self.assertIsNone(snapshot["channel_source"])
        self.assertFalse(snapshot["mediareq26_open_sent"])
        self.assertIsNone(snapshot["mediareq26_open_channel"])
        self.assertFalse(snapshot["rtp_received"])
        self.assertIsNone(snapshot["rtp_packet_count"])
        self.assertIsNone(snapshot["rtp_payload_type"])
        self.assertFalse(snapshot["h264_detected"])
        self.assertIsNone(snapshot["video_width"])
        self.assertIsNone(snapshot["video_height"])
        self.assertIsNone(snapshot["first_rtp_at"])
        self.assertFalse(snapshot["stop_sent"])
        self.assertIsNone(snapshot["stop_channel"])
        self.assertFalse(snapshot["channel_closed"])
        self.assertFalse(snapshot["cleanup_complete"])
        self.assertFalse(snapshot["capabilities_seen"])
        self.assertFalse(snapshot["capabilities_parse_ok"])
        self.assertFalse(snapshot["capabilities_call_match"])
        self.assertFalse(snapshot["capabilities_video_requested"])
        self.assertIsNone(snapshot["trigger_reject_stage"])
        self.assertIsNone(snapshot["capabilities_candidate_count"])
        self.assertIsNone(snapshot["attach_failure_reason"])

    def test_full_call_lifecycle_binds_every_field_to_the_call_generation(
        self,
    ) -> None:
        diag = MediaCallDiagnostics(clock=lambda: "2026-09-20T12:00:00+00:00")
        for line in (
            "R42_CALL_GENERATION=1",
            "R42_MEDIA_CHANNEL_ID=4110",
            "R42_CALL_GENERATION=1",
            "R42_MEDIAREQ26_OPEN_CHANNEL=4110",
            "P80_VIDEO_RTP_FORWARDING=PASS",
            "P80_VIDEO_RTP_PACKETS=1",
            # p116_print_summary() prints PT_SET on the very first packet.
            "P116_VIDEO_PT_SET=99",
            "P116_VIDEO_SPS_COUNT=1",
            "P80_VIDEO_RTP_PACKETS=50",
            "R42_CALL_GENERATION=1",
            "R42_MEDIA_STOP_CHANNEL=4110",
            "R42_LISTENER_RTP_FORWARDING_ARMED=false",
            "R42_CALL_GENERATION=1",
            "R42_MEDIA_CHANNEL_CLOSED=true",
        ):
            diag.observe_line(line)

        snapshot = diag.snapshot()
        self.assertEqual(snapshot["call_generation"], 1)
        self.assertEqual(snapshot["media_channel"], 4110)
        self.assertEqual(snapshot["channel_source"], "RUNTIME_CALL_BOUND")
        self.assertTrue(snapshot["mediareq26_open_sent"])
        self.assertEqual(snapshot["mediareq26_open_channel"], 4110)
        self.assertTrue(snapshot["rtp_received"])
        self.assertEqual(snapshot["rtp_packet_count"], 50)
        self.assertEqual(snapshot["rtp_payload_type"], 99)
        self.assertTrue(snapshot["h264_detected"])
        self.assertEqual(snapshot["first_rtp_at"], "2026-09-20T12:00:00+00:00")
        self.assertTrue(snapshot["stop_sent"])
        self.assertEqual(snapshot["stop_channel"], 4110)
        self.assertTrue(snapshot["channel_closed"])
        self.assertTrue(snapshot["cleanup_complete"])

    def test_rtp_payload_type_is_none_without_a_pt_set_marker(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("P80_VIDEO_RTP_FORWARDING=PASS")
        diag.observe_line("P80_VIDEO_RTP_PACKETS=1")
        self.assertTrue(diag.snapshot()["rtp_received"])
        self.assertIsNone(diag.snapshot()["rtp_payload_type"])

    def test_rtp_payload_type_is_parsed_from_runtime_pt_set_not_a_literal(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("P116_VIDEO_PT_SET=97")
        self.assertEqual(diag.snapshot()["rtp_payload_type"], 97)

    def test_rtp_payload_type_is_none_for_ambiguous_pt_set_shapes(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("P116_VIDEO_PT_SET=99")
        self.assertEqual(diag.snapshot()["rtp_payload_type"], 99)

        # NONE (no payload type observed yet) must read as unknown, not 0/99.
        diag.observe_line("P116_VIDEO_PT_SET=NONE")
        self.assertIsNone(diag.snapshot()["rtp_payload_type"])

        diag.observe_line("P116_VIDEO_PT_SET=99")
        self.assertEqual(diag.snapshot()["rtp_payload_type"], 99)

        # More than one observed payload type is no longer an unambiguous
        # scalar; must fall back to unknown rather than pick one or guess.
        diag.observe_line("P116_VIDEO_PT_SET=99,97")
        self.assertIsNone(diag.snapshot()["rtp_payload_type"])

    def test_rtp_payload_type_out_of_7bit_range_is_rejected(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("P116_VIDEO_PT_SET=128")
        self.assertIsNone(diag.snapshot()["rtp_payload_type"])
        diag.observe_line("P116_VIDEO_PT_SET=999")
        self.assertIsNone(diag.snapshot()["rtp_payload_type"])

    def test_media_diagnostics_module_never_assigns_payload_type_a_literal(
        self,
    ) -> None:
        source = MEDIA_DIAGNOSTICS.read_text(encoding="utf-8")
        self.assertNotIn("_rtp_payload_type = 99", source)
        # The only assignment sites for the private attribute are the reset
        # default and the parsed-from-runtime-marker call.
        assignment_re = re.compile(r"self\._rtp_payload_type\s*=\s*(.+)")
        rhs_values = assignment_re.findall(source)
        self.assertTrue(rhs_values, "expected at least one assignment site")
        for rhs in rhs_values:
            rhs = rhs.strip()
            self.assertTrue(
                rhs == "None"
                or rhs.startswith("self._parse_single_video_payload_type("),
                f"unexpected literal assignment to rtp_payload_type: {rhs!r}",
            )

    def test_new_call_generation_wipes_prior_call_evidence(self) -> None:
        diag = MediaCallDiagnostics()
        for line in (
            "R42_CALL_GENERATION=1",
            "R42_MEDIA_CHANNEL_ID=100",
            "P80_VIDEO_RTP_FORWARDING=PASS",
            "P80_VIDEO_RTP_PACKETS=200",
            "R42_CALL_GENERATION=1",
            "R42_MEDIA_STOP_CHANNEL=100",
            "R42_CALL_GENERATION=1",
            "R42_MEDIA_CHANNEL_CLOSED=true",
        ):
            diag.observe_line(line)

        first = diag.snapshot()
        self.assertEqual(first["media_channel"], 100)
        self.assertTrue(first["channel_closed"])
        self.assertTrue(first["rtp_received"])

        diag.observe_line("R42_CALL_GENERATION=2")
        second = diag.snapshot()
        self.assertEqual(second["call_generation"], 2)
        self.assertIsNone(second["media_channel"])
        self.assertIsNone(second["channel_source"])
        self.assertFalse(second["rtp_received"])
        self.assertIsNone(second["rtp_packet_count"])
        self.assertFalse(second["channel_closed"])
        self.assertFalse(second["cleanup_complete"])
        self.assertIsNone(second["stop_channel"])

        diag.observe_line("R42_MEDIA_CHANNEL_ID=555")
        third = diag.snapshot()
        self.assertEqual(third["media_channel"], 555)
        self.assertEqual(third["channel_source"], "RUNTIME_CALL_BOUND")

    def test_older_or_equal_generation_marker_never_wipes_current_evidence(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=5")
        diag.observe_line("R42_MEDIA_CHANNEL_ID=9")

        # Same-generation re-announcement must be a no-op, not a reset.
        diag.observe_line("R42_CALL_GENERATION=5")
        self.assertEqual(diag.snapshot()["media_channel"], 9)

        # An out-of-order/stale generation marker must never roll evidence
        # backward or wipe the current call.
        diag.observe_line("R42_CALL_GENERATION=3")
        snapshot = diag.snapshot()
        self.assertEqual(snapshot["call_generation"], 5)
        self.assertEqual(snapshot["media_channel"], 9)

    def test_process_restart_reset_is_explicit_not_generation_comparison(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=9")
        diag.observe_line("R42_MEDIA_CHANNEL_ID=42")

        diag.reset()
        self.assertIsNone(diag.snapshot()["call_generation"])

        # A restarted native process starts call_generation from scratch;
        # arm_for_generation's ">" comparison alone would refuse this.
        diag.observe_line("R42_CALL_GENERATION=1")
        self.assertEqual(diag.snapshot()["call_generation"], 1)

    def test_channel_fields_require_runtime_allocation_never_a_literal(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        self.assertIsNone(diag.snapshot()["media_channel"])
        self.assertIsNone(diag.snapshot()["channel_source"])

        # The forbidden capture-channel literal must never populate the
        # field even if it appeared verbatim on the wire.
        diag.observe_line("R42_MEDIA_CHANNEL_ID=0x0C4A")
        self.assertIsNone(diag.snapshot()["media_channel"])
        self.assertIsNone(diag.snapshot()["channel_source"])

        diag.observe_line("R42_MEDIA_CHANNEL_ID=777")
        self.assertEqual(diag.snapshot()["media_channel"], 777)
        self.assertEqual(diag.snapshot()["channel_source"], "RUNTIME_CALL_BOUND")

    def test_evidence_without_a_bound_generation_is_dropped_not_recorded(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_MEDIA_CHANNEL_ID=100")
        diag.observe_line("P80_VIDEO_RTP_FORWARDING=PASS")
        snapshot = diag.snapshot()
        self.assertIsNone(snapshot["media_channel"])
        self.assertIsNone(snapshot["call_generation"])
        self.assertFalse(snapshot["rtp_received"])

    def test_unsafe_or_malformed_values_are_redacted_or_ignored_not_fatal(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        for malformed in (
            "R42_MEDIA_CHANNEL_ID=not-a-number",
            "R42_MEDIA_CHANNEL_ID=1; rm -rf /",
            "R42_MEDIA_CHANNEL_ID=",
            "R42_MEDIA_CHANNEL_ID=00112233445566778899aabbccddeeff",
            "R42_MEDIA_CHANNEL_ID=deadbeefCOMELIT_VIP_TOKEN",
        ):
            # Must never raise; must never apply an unsafe value.
            diag.observe_line(malformed)
        self.assertIsNone(diag.snapshot()["media_channel"])

    def test_h264_detection_requires_positive_evidence_count(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("P116_VIDEO_SPS_COUNT=0")
        self.assertFalse(diag.snapshot()["h264_detected"])
        diag.observe_line("P116_VIDEO_FUA_COUNT=3")
        self.assertTrue(diag.snapshot()["h264_detected"])

    def test_unrecognized_keys_and_prefixes_are_not_consumed(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        self.assertFalse(diag.observe_line("TOKEN=abc123"))
        self.assertFalse(diag.observe_line("V4_DOOR_WRITE_COUNT=5"))
        self.assertFalse(diag.observe_line("no-equals-sign-here"))

    def test_snapshot_never_contains_injected_or_secret_looking_substrings(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        poison = (
            "R42_MEDIA_CHANNEL_ID=COMELIT_VIP_TOKEN=deadbeefdeadbeefdeadbeefdeadbeef",
            "R42_MEDIAREQ26_OPEN_CHANNEL=<script>alert(1)</script>",
            "R42_MEDIA_STOP_CHANNEL=../../etc/passwd",
        )
        for line in poison:
            diag.observe_line(line)
        for value in diag.snapshot().values():
            if isinstance(value, str):
                self.assertNotIn("TOKEN", value)
                self.assertNotIn("script", value)
                self.assertNotIn("passwd", value)


class CapabilitiesTriggerDiagnosticsUnitTests(unittest.TestCase):
    """Round 2 (failure forensic): CAPABILITIES-candidate classification."""

    def test_full_candidate_match_reports_all_new_fields(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_SEEN=true")
        diag.observe_line("R42_CAPABILITIES_PARSE_OK=true")
        diag.observe_line("R42_CAPABILITIES_CALL_MATCH=true")
        diag.observe_line("R42_CAPABILITIES_VIDEO_REQUESTED=true")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=NONE")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_COUNT=1")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=OPEN_SENT")

        snapshot = diag.snapshot()
        self.assertTrue(snapshot["capabilities_seen"])
        self.assertTrue(snapshot["capabilities_parse_ok"])
        self.assertTrue(snapshot["capabilities_call_match"])
        self.assertTrue(snapshot["capabilities_video_requested"])
        self.assertEqual(snapshot["trigger_reject_stage"], "OPEN_SENT")
        self.assertEqual(snapshot["capabilities_candidate_count"], 1)

    def test_video_bit_clear_rejection_reports_call_match_but_not_video(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_SEEN=true")
        diag.observe_line("R42_CAPABILITIES_PARSE_OK=true")
        diag.observe_line("R42_CAPABILITIES_CALL_MATCH=true")
        diag.observe_line("R42_CAPABILITIES_VIDEO_REQUESTED=false")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=VIDEO_BIT_CLEAR")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_COUNT=1")

        snapshot = diag.snapshot()
        self.assertTrue(snapshot["capabilities_seen"])
        self.assertTrue(snapshot["capabilities_call_match"])
        self.assertFalse(snapshot["capabilities_video_requested"])
        self.assertEqual(snapshot["trigger_reject_stage"], "VIDEO_BIT_CLEAR")

    def test_no_candidate_frame_at_all_leaves_fields_at_default(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        snapshot = diag.snapshot()
        self.assertFalse(snapshot["capabilities_seen"])
        self.assertFalse(snapshot["capabilities_parse_ok"])
        self.assertFalse(snapshot["capabilities_call_match"])
        self.assertFalse(snapshot["capabilities_video_requested"])
        self.assertIsNone(snapshot["trigger_reject_stage"])
        self.assertIsNone(snapshot["capabilities_candidate_count"])

    def test_trigger_reject_stage_whitelist_rejects_unknown_values(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        for bogus in (
            "MAYBE",
            "none",  # wrong case
            "NO_LIVE_CALL; rm -rf /",
            "",
            "QUEUE_REJECTED,OPEN_SENT",
        ):
            diag.observe_line(f"R42_TRIGGER_REJECT_STAGE={bogus}")
            self.assertIsNone(diag.snapshot()["trigger_reject_stage"])

        # A legitimate whitelist member still works after rejecting bogus ones.
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=NO_LIVE_CALL")
        self.assertEqual(diag.snapshot()["trigger_reject_stage"], "NO_LIVE_CALL")

    def test_all_eleven_whitelisted_reject_stages_are_accepted(self) -> None:
        for stage in (
            "NONE",
            "NO_WRITER",
            "ENVELOPE",
            "FLAG",
            "OPCODE",
            "LENGTH",
            "NO_LIVE_CALL",
            "CONNECTION_MISMATCH",
            "VIDEO_BIT_CLEAR",
            "QUEUE_REJECTED",
            "OPEN_SENT",
        ):
            with self.subTest(stage=stage):
                diag = MediaCallDiagnostics()
                diag.observe_line("R42_CALL_GENERATION=1")
                diag.observe_line(f"R42_TRIGGER_REJECT_STAGE={stage}")
                self.assertEqual(diag.snapshot()["trigger_reject_stage"], stage)

    def test_new_call_generation_wipes_stale_capabilities_evidence(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_SEEN=true")
        diag.observe_line("R42_CAPABILITIES_CALL_MATCH=true")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=VIDEO_BIT_CLEAR")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_COUNT=3")
        self.assertTrue(diag.snapshot()["capabilities_seen"])

        diag.observe_line("R42_CALL_GENERATION=2")
        snapshot = diag.snapshot()
        self.assertEqual(snapshot["call_generation"], 2)
        self.assertFalse(snapshot["capabilities_seen"])
        self.assertFalse(snapshot["capabilities_call_match"])
        self.assertIsNone(snapshot["trigger_reject_stage"])
        self.assertIsNone(snapshot["capabilities_candidate_count"])

    def test_capabilities_evidence_without_a_bound_generation_is_dropped(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_SEEN=true")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=NO_LIVE_CALL")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_COUNT=1")
        snapshot = diag.snapshot()
        self.assertIsNone(snapshot["call_generation"])
        self.assertFalse(snapshot["capabilities_seen"])
        self.assertIsNone(snapshot["trigger_reject_stage"])
        self.assertIsNone(snapshot["capabilities_candidate_count"])

    def test_candidate_count_is_parsed_as_int_not_string(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_COUNT=8")
        self.assertEqual(diag.snapshot()["capabilities_candidate_count"], 8)
        self.assertIsInstance(diag.snapshot()["capabilities_candidate_count"], int)

    def test_stronger_capabilities_evidence_survives_later_noise(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_SEEN=true")
        diag.observe_line("R42_CAPABILITIES_PARSE_OK=true")
        diag.observe_line("R42_CAPABILITIES_CALL_MATCH=true")
        diag.observe_line("R42_CAPABILITIES_VIDEO_REQUESTED=true")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_COUNT=3")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=OPEN_SENT")

        # Later unrelated traffic in the same call generation must not erase
        # the deepest evidence already observed for the real candidate.
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_SEEN=false")
        diag.observe_line("R42_CAPABILITIES_PARSE_OK=false")
        diag.observe_line("R42_CAPABILITIES_CALL_MATCH=false")
        diag.observe_line("R42_CAPABILITIES_VIDEO_REQUESTED=false")
        diag.observe_line("R42_CAPABILITIES_CANDIDATE_COUNT=0")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=OPCODE")

        snapshot = diag.snapshot()
        self.assertTrue(snapshot["capabilities_seen"])
        self.assertTrue(snapshot["capabilities_parse_ok"])
        self.assertTrue(snapshot["capabilities_call_match"])
        self.assertTrue(snapshot["capabilities_video_requested"])
        self.assertEqual(snapshot["capabilities_candidate_count"], 3)
        self.assertEqual(snapshot["trigger_reject_stage"], "OPEN_SENT")

    def test_candidate_count_never_regresses_within_generation(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        for count in (1, 4, 2, 0, 3):
            diag.observe_line(f"R42_CAPABILITIES_CANDIDATE_COUNT={count}")
        self.assertEqual(diag.snapshot()["capabilities_candidate_count"], 4)

    def test_terminal_trigger_result_implies_full_predicate_evidence(self) -> None:
        # OPEN_SENT / QUEUE_REJECTED are emitted by the functional trigger
        # after every CAPABILITIES predicate has already passed. Even if the
        # candidate-detail log budget is exhausted, the terminal marker is
        # sufficient bounded evidence for those predicates.
        for stage in ("QUEUE_REJECTED", "OPEN_SENT"):
            with self.subTest(stage=stage):
                diag = MediaCallDiagnostics()
                diag.observe_line("R42_CALL_GENERATION=1")
                diag.observe_line(f"R42_TRIGGER_REJECT_STAGE={stage}")
                snapshot = diag.snapshot()
                self.assertTrue(snapshot["capabilities_seen"])
                self.assertTrue(snapshot["capabilities_parse_ok"])
                self.assertTrue(snapshot["capabilities_call_match"])
                self.assertTrue(snapshot["capabilities_video_requested"])
                self.assertEqual(snapshot["trigger_reject_stage"], stage)

    def test_invalid_or_weaker_stage_does_not_erase_valid_deeper_stage(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=VIDEO_BIT_CLEAR")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=NOT_A_STAGE")
        diag.observe_line("R42_TRIGGER_REJECT_STAGE=ENVELOPE")
        self.assertEqual(
            diag.snapshot()["trigger_reject_stage"], "VIDEO_BIT_CLEAR"
        )

    def test_attach_failure_reason_accepts_only_whitelisted_values(self) -> None:
        diag = MediaCallDiagnostics()
        diag.set_attach_failure_reason("attached_media_open_not_confirmed")
        self.assertEqual(
            diag.snapshot()["attach_failure_reason"],
            "attached_media_open_not_confirmed",
        )
        diag.set_attach_failure_reason("some_unexpected_exception_message")
        self.assertIsNone(diag.snapshot()["attach_failure_reason"])
        diag.set_attach_failure_reason(None)
        self.assertIsNone(diag.snapshot()["attach_failure_reason"])

    def test_attach_failure_reason_is_not_populated_from_native_markers(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        # A native marker line can never set attach_failure_reason, even if
        # it happens to spell a whitelisted reason string as its value.
        consumed = diag.observe_line(
            "R42_ATTACH_FAILURE_REASON=attached_media_open_not_confirmed"
        )
        self.assertFalse(consumed)
        self.assertIsNone(diag.snapshot()["attach_failure_reason"])

    def test_attach_failure_reason_is_wiped_on_new_call_generation(self) -> None:
        diag = MediaCallDiagnostics()
        diag.observe_line("R42_CALL_GENERATION=1")
        diag.set_attach_failure_reason("listener_not_ready")
        self.assertEqual(
            diag.snapshot()["attach_failure_reason"], "listener_not_ready"
        )
        diag.observe_line("R42_CALL_GENERATION=2")
        self.assertIsNone(diag.snapshot()["attach_failure_reason"])

    def test_all_twelve_whitelisted_attach_failure_reasons_are_accepted(
        self,
    ) -> None:
        diag = MediaCallDiagnostics()
        reasons = (
            "attached_media_open_not_confirmed",
            "listener_not_ready",
            "media_start_not_confirmed",
            "unsupported_attached_media_panel",
            "media_session_state_mismatch",
            "media_session_transition_busy",
            "attached_inbound_media_busy",
            "listener_pause_not_confirmed",
            "unsupported_media_panel",
            "invalid_media_reason",
            "invalid_stop_reason",
            "unknown",
        )
        self.assertEqual(len(reasons), 12)
        for reason in reasons:
            diag.set_attach_failure_reason(reason)
            self.assertEqual(diag.snapshot()["attach_failure_reason"], reason)


class RuntimeStatusMediaDiagnosticsTests(unittest.TestCase):
    """Integration tests through ComelitRingRuntime.status() / _async_read_output()."""

    def test_status_exposes_media_diagnostics_with_all_required_fields(self) -> None:
        import asyncio

        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)
        status = runtime.status()
        self.assertIn("media_diagnostics", status)
        diagnostics = status["media_diagnostics"]
        self.assertEqual(set(diagnostics), set(ALL_DIAGNOSTICS_FIELDS))
        # Existing fields must still be present and unrenamed.
        for key in (
            "attached_media_busy",
            "attached_media_open",
            "listener_ready",
            "last_error",
        ):
            self.assertIn(key, status)

        async def run() -> None:
            await _feed_lines(
                runtime,
                [
                    "V4_RING_LISTENER_READY=true",
                    "R42_CALL_GENERATION=1",
                    "R42_MEDIA_CHANNEL_ALLOCATED=true",
                    "R42_CAPTURE_CHANNEL_LITERAL_USED=false",
                    "R42_CALL_GENERATION=1",
                    "R42_MEDIA_CHANNEL_ID=4110",
                    "R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED",
                    "R42_CALL_GENERATION=1",
                    "R42_MEDIAREQ26_OPEN_CHANNEL=4110",
                    "R42_ATTACHED_MEDIA_ACTIVE=true",
                    "P80_VIDEO_RTP_FORWARDING=PASS",
                    "P80_VIDEO_RTP_PACKETS=1",
                    "P116_VIDEO_PT_SET=99",
                    "P116_VIDEO_SPS_COUNT=1",
                    "P80_VIDEO_RTP_PACKETS=50",
                ],
            )

        asyncio.run(run())
        live = runtime.status()["media_diagnostics"]
        self.assertEqual(live["call_generation"], 1)
        self.assertEqual(live["media_channel"], 4110)
        self.assertEqual(live["channel_source"], "RUNTIME_CALL_BOUND")
        self.assertTrue(live["mediareq26_open_sent"])
        self.assertEqual(live["mediareq26_open_channel"], 4110)
        self.assertTrue(live["rtp_received"])
        self.assertEqual(live["rtp_packet_count"], 50)
        self.assertEqual(live["rtp_payload_type"], 99)
        self.assertTrue(live["h264_detected"])
        self.assertIsNone(live["video_width"])
        self.assertIsNone(live["video_height"])
        self.assertFalse(live["stop_sent"])
        self.assertFalse(live["channel_closed"])
        self.assertFalse(live["cleanup_complete"])

    def test_next_call_generation_never_shows_prior_call_as_current(self) -> None:
        import asyncio

        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        async def run() -> None:
            await _feed_lines(
                runtime,
                [
                    "R42_CALL_GENERATION=1",
                    "R42_MEDIA_CHANNEL_ID=100",
                    "P80_VIDEO_RTP_FORWARDING=PASS",
                    "P80_VIDEO_RTP_PACKETS=10",
                    "R42_CALL_GENERATION=1",
                    "R42_MEDIA_STOP_CHANNEL=100",
                    "R42_LISTENER_RTP_FORWARDING_ARMED=false",
                    "R42_CALL_GENERATION=1",
                    "R42_MEDIA_CHANNEL_CLOSED=true",
                ],
            )

        asyncio.run(run())
        finished = runtime.status()["media_diagnostics"]
        self.assertTrue(finished["cleanup_complete"])
        self.assertEqual(finished["media_channel"], 100)

        async def run_next() -> None:
            await _feed_lines(
                runtime,
                [
                    "R42_CALL_GENERATION=2",
                    "R42_MEDIA_CHANNEL_ID=250",
                ],
            )

        asyncio.run(run_next())
        current = runtime.status()["media_diagnostics"]
        self.assertEqual(current["call_generation"], 2)
        self.assertEqual(current["media_channel"], 250)
        self.assertFalse(current["cleanup_complete"])
        self.assertFalse(current["channel_closed"])
        self.assertIsNone(current["stop_channel"])

    def test_async_start_resets_media_diagnostics_state(self) -> None:
        tree_source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("self._media_diagnostics.reset()", tree_source)
        self.assertIn("self._media_diagnostics.observe_line(line)", tree_source)
        self.assertIn('"media_diagnostics": self._media_diagnostics.snapshot()', tree_source)

    def test_frozen_sigusr2_and_door_contracts_are_unaffected(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("os.kill(process.pid, signal.SIGUSR2)", source)
        self.assertIn("os.kill(process.pid, signal.SIGUSR1)", source)
        self.assertEqual(source.count("os.kill(process.pid, signal.SIGUSR1)"), 1)


class R42BCanaryMarkerSourceGateTests(unittest.TestCase):
    """Source-level gates: markers present, deterministic, no capture literal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base_source = DOOR_SOURCE.read_text(encoding="utf-8")
        cls.candidate = r42b.transform(cls.base_source)
        cls.builder_source = BUILDER.read_text(encoding="utf-8")

    def test_new_markers_are_present_exactly_once_each(self) -> None:
        candidate = self.candidate
        for marker, expected_count in (
            ("R42_MEDIA_CHANNEL_ID=%u", 1),
            ("R42_MEDIAREQ26_OPEN_CHANNEL=%u", 1),
            ("R42_MEDIA_STOP_CHANNEL=%u", 1),
        ):
            self.assertEqual(candidate.count(marker), expected_count)
        # One generation marker at capture, allocation, mediareq-open, stop
        # and channel-close each.
        self.assertEqual(candidate.count("R42_CALL_GENERATION=%u"), 5)

    def test_generation_source_transform_is_deterministic(self) -> None:
        self.assertEqual(self.candidate, r42b.transform(self.base_source))

    def test_no_capture_literal_reaches_the_new_markers(self) -> None:
        for capture_literal in ("0x0C4A", "0x4A5A", "0xCA5A"):
            self.assertNotIn(capture_literal, self.candidate)

    def test_add_media_diagnostics_markers_fails_closed_on_missing_anchor(
        self,
    ) -> None:
        broken = self.candidate.replace(
            'printf("R42_MEDIA_CHANNEL_ALLOCATED=true\\n");', "", 1
        )
        with self.assertRaises(RuntimeError):
            r42b.add_media_diagnostics_markers(broken)

    def test_builder_gates_cover_the_new_scalar_markers_source_and_binary(
        self,
    ) -> None:
        source = self.builder_source
        for marker in (
            "R42_CALL_GENERATION=%u",
            "R42_MEDIA_CHANNEL_ID=%u",
            "R42_MEDIAREQ26_OPEN_CHANNEL=%u",
            "R42_MEDIA_STOP_CHANNEL=%u",
        ):
            self.assertGreaterEqual(
                source.count(marker),
                2,
                f"expected {marker!r} in both the source-level and "
                "binary-level (strings) marker gate loops",
            )
        self.assertIn("CAPTURE_LITERAL_GATE=PASS", source)
        self.assertIn("BINARY_CAPTURE_LITERAL_GATE=PASS", source)

    def test_final_listener_gate_requires_the_new_markers(self) -> None:
        with self.assertRaises(RuntimeError):
            r42b._assert_final_listener_gates(
                self.candidate.replace("R42_MEDIA_CHANNEL_ID=%u", "", 1)
            )


class R42BCapabilitiesTriggerDiagnosticsSourceGateTests(unittest.TestCase):
    """Round 2 (failure forensic): the CAPABILITIES-candidate native overlay.

    Verifies the new native diagnostics are bounded/read-only and that they
    introduce NO functional/control-flow change: the real OPEN call site is
    invoked exactly as many times as before, no retry/timeout is added, and
    no capture literal appears.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.base_source = DOOR_SOURCE.read_text(encoding="utf-8")
        # r42.transform()'s own output, i.e. the candidate BEFORE any R42-b
        # canary-observability overlay, to get a "before" baseline for the
        # r42_queue_media_channel_open( call-count invariant.
        r35_candidate = r42b.r35.transform(r42b.add_listener_rtp_bridge(cls.base_source))
        r35_candidate = r42b._replace_once(
            r35_candidate,
            r42b._R35_ARM_OLD,
            r42b._R35_ARM_NEW,
            "test fixture arm hook",
        )
        r36_candidate = r42b.r36.transform(r35_candidate)
        r37_candidate = r42b.add_listener_r37(r36_candidate)
        cls.pre_capabilities_diag_candidate = r42b.r42.transform(r37_candidate)
        cls.candidate = r42b.transform(cls.base_source)

    def test_open_call_count_is_unchanged_by_the_new_diagnostics(self) -> None:
        before = self.pre_capabilities_diag_candidate.count(
            "r42_queue_media_channel_open("
        )
        after = self.candidate.count("r42_queue_media_channel_open(")
        self.assertEqual(before, after)
        # Sanity: the real call site does exist exactly once (definition +
        # the one call site inside the functional trigger).
        self.assertGreaterEqual(before, 1)

    def test_new_markers_present_with_expected_multiplicities(self) -> None:
        candidate = self.candidate
        self.assertEqual(
            candidate.count("R42_CAPABILITIES_CANDIDATE_SEEN=true"), 1
        )
        self.assertEqual(candidate.count("R42_CAPABILITIES_PARSE_OK=%s"), 1)
        self.assertEqual(candidate.count("R42_CAPABILITIES_CALL_MATCH=%s"), 1)
        self.assertEqual(
            candidate.count("R42_CAPABILITIES_VIDEO_REQUESTED=%s"), 1
        )
        self.assertEqual(candidate.count("R42_CAPABILITIES_CANDIDATE_COUNT=%u"), 1)
        # Once from the pre-candidate rejection block (its own
        # once-per-stage-per-generation budget), once from the
        # candidate-classification block (may resolve to NONE), once more from
        # the real trigger-outcome site (OPEN_SENT/QUEUE_REJECTED).
        self.assertEqual(candidate.count("R42_TRIGGER_REJECT_STAGE=%s"), 3)

    def test_reject_stage_enum_values_match_the_required_whitelist(self) -> None:
        region = self.candidate.split(
            "/* R42_CAPABILITIES_DIAGNOSTICS_BEGIN */", 1
        )[1].split("/* R42_CAPABILITIES_DIAGNOSTICS_END */", 1)[0]
        state_region = self.candidate.split(
            "/* R42_CAPABILITIES_DIAGNOSTICS_STATE_BEGIN */", 1
        )[1].split("/* R42_CAPABILITIES_DIAGNOSTICS_STATE_END */", 1)[0]
        # The pre-candidate stage names live in the pure helper region, the
        # candidate stage names in the inline block; an observable stage must
        # appear as a literal in one of them.
        for stage in (
            "NONE",
            "NO_WRITER",
            "ENVELOPE",
            "FLAG",
            "OPCODE",
            "LENGTH",
            "NO_LIVE_CALL",
            "CONNECTION_MISMATCH",
            "VIDEO_BIT_CLEAR",
        ):
            self.assertTrue(
                f'"{stage}"' in region or f'"{stage}"' in state_region,
                f"stage {stage} is not observable",
            )
        self.assertIn('"OPEN_SENT"', self.candidate)
        self.assertIn('"QUEUE_REJECTED"', self.candidate)

    def test_detail_lines_are_bounded_to_eight_per_generation(self) -> None:
        region = self.candidate.split(
            "/* R42_CAPABILITIES_DIAGNOSTICS_BEGIN */", 1
        )[1].split("/* R42_CAPABILITIES_DIAGNOSTICS_END */", 1)[0]
        normalized = " ".join(region.split())
        self.assertIn("R42_DIAG_DETAIL_LINE_LIMIT", region)
        self.assertIn(
            "r42_diag_detail_lines_printed < R42_DIAG_DETAIL_LINE_LIMIT",
            normalized,
        )
        self.assertIn("#define R42_DIAG_DETAIL_LINE_LIMIT 8u", self.candidate)
        # The candidate counter keeps incrementing regardless of the detail
        # line cap.
        self.assertIn("r42_diag_candidate_count++;", region)
        # Pre-candidate rejection stages are bounded by their own
        # once-per-stage-per-generation mask rather than by this budget.
        self.assertIn("r42_diag_pre_seen_mask", self.candidate)
        normalized_pre = " ".join(
            self.candidate.split(
                "/* R42_CAPABILITIES_DIAGNOSTICS_BEGIN */", 1
            )[1]
            .split("/* R42_CAPABILITIES_DIAGNOSTICS_END */", 1)[0]
            .split()
        )
        self.assertIn(
            "r42_diag_pre_stage_should_emit( &r42_diag_pre_seen_mask, r42_diag_pre_bit)",
            normalized_pre,
        )

    def test_diagnostics_never_call_the_real_open_writer_or_retry(self) -> None:
        region = self.candidate.split(
            "/* R42_CAPABILITIES_DIAGNOSTICS_BEGIN */", 1
        )[1].split("/* R42_CAPABILITIES_DIAGNOSTICS_END */", 1)[0]
        self.assertNotIn("r42_queue_media_channel_open(", region)
        self.assertNotIn("r35_send_open(", region)
        self.assertNotIn("g_timeout_add", region)
        self.assertNotIn("continue;", region)
        self.assertNotIn("return", region)
        self.assertNotIn("retry", region.lower())

    def test_no_capture_literal_in_capabilities_diagnostics(self) -> None:
        for capture_literal in ("0x0C4A", "0x4A5A", "0xCA5A"):
            self.assertNotIn(capture_literal, self.candidate)

    def test_transform_is_deterministic(self) -> None:
        self.assertEqual(self.candidate, r42b.transform(self.base_source))

    def test_add_capabilities_trigger_diagnostics_fails_closed_on_missing_anchor(
        self,
    ) -> None:
        broken = self.candidate.replace(
            "static R42AttachedMediaStage r42_media_stage = R42_MEDIA_IDLE;\n",
            "",
            1,
        )
        with self.assertRaises(RuntimeError):
            r42b.add_capabilities_trigger_diagnostics(broken)

    def test_final_listener_gate_requires_capabilities_markers(self) -> None:
        with self.assertRaises(RuntimeError):
            r42b._assert_final_listener_gates(
                self.candidate.replace(
                    "R42_CAPABILITIES_CANDIDATE_SEEN=true", "", 1
                )
            )


class AttachFailureReasonWiringTests(unittest.TestCase):
    """The transport attach-failure reason must reach ``media_diagnostics``.

    Covers the second half of the DEV corrective: ``attach_failure_reason`` is
    a Python-transport value, so its *wiring* (not only its sanitizer) is what
    lets the next canary tell "the native side never confirmed the attached
    media channel" apart from a shim, SDP or session failure - instead of
    having to infer it from the elapsed time as this round had to.
    """

    def test_runtime_binds_the_coordinator_recorder_and_reports_it(self) -> None:
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        class FakeCoordinator:
            def __init__(self) -> None:
                self.recorder = None

            def set_attach_failure_recorder(self, recorder: object) -> None:
                self.recorder = recorder

            def status(self) -> dict[str, object]:
                return {}

        coordinator = FakeCoordinator()
        runtime.set_ring_media_coordinator(coordinator)
        self.assertIsNotNone(coordinator.recorder)
        # Nothing is fabricated before a real failure.
        self.assertIsNone(
            runtime.status()["media_diagnostics"]["attach_failure_reason"]
        )

        coordinator.recorder("attached_media_open_not_confirmed")
        self.assertEqual(
            runtime.status()["media_diagnostics"]["attach_failure_reason"],
            "attached_media_open_not_confirmed",
        )

        # An unexpected exception-derived string is dropped, never stored.
        coordinator.recorder("ComelitAttachedMediaError: raw detail")
        self.assertIsNone(
            runtime.status()["media_diagnostics"]["attach_failure_reason"]
        )

    def test_synthetic_coordinator_is_bound_and_hookless_objects_are_safe(
        self,
    ) -> None:
        module = _load_runtime_module()
        runtime = _status_ready_runtime_instance(module)

        class FakeCoordinator:
            def __init__(self) -> None:
                self.recorder = None

            def set_attach_failure_recorder(self, recorder: object) -> None:
                self.recorder = recorder

        synthetic = FakeCoordinator()
        runtime.set_synthetic_ring_media_coordinator(synthetic)
        self.assertIsNotNone(synthetic.recorder)

        # A coordinator or test double without the hook must not break the
        # existing setter contract.
        runtime.set_ring_media_coordinator(object())
        runtime.set_ring_media_coordinator(None)

        synthetic.recorder("media_start_not_confirmed")
        self.assertEqual(
            runtime.status()["media_diagnostics"]["attach_failure_reason"],
            "media_start_not_confirmed",
        )

    def test_ring_media_reports_the_reason_from_the_failure_branch(self) -> None:
        source = RING_MEDIA.read_text(encoding="utf-8")
        self.assertIn("def set_attach_failure_recorder(", source)
        # Exactly one call site, inside the media-start failure branch, and
        # the frozen failure contract itself stays unchanged.
        self.assertEqual(source.count("recorder(str(exc))"), 1)
        self.assertIn('recording_failure_reason = "media_start_failed"', source)


if __name__ == "__main__":
    unittest.main()
