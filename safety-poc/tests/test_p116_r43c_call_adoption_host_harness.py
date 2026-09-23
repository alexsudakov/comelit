#!/usr/bin/env python3
"""P116/R43C offline C host-harness tests for native call-adoption signaling.

The harness is assembled from the exact R35/R36/R45 dependency-free C regions plus
the R43C harness body, compiled with -std=c99 -Wall -Wextra -pedantic, and run
offline.  Nothing here opens a socket, touches Home Assistant, or reaches a
Comelit host.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
HARNESS = Path(__file__).resolve().parent / "native" / "p116_r43c_call_adoption_host_harness.c"
REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_TRANSFORM = MEDIA / "entrance_p116_r42b_listener_attached_media_transform.py"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402
import entrance_p116_r36_attached_media_trigger_transform as r36  # noqa: E402
import entrance_p116_r45_call_adoption_core as r45  # noqa: E402

SCENARIO_MARKERS = (
    "R43C_01_CALL_CAPTURE",
    "R43C_02_CAPABILITIES_BEFORE_ACK_REJECTED",
    "R43C_03_ALERTING_BEFORE_CAPABILITIES_REJECTED",
    "R43C_04_INVITE_ACK_EMITTED",
    "R43C_05_INVITE_ACK_EXACT_BYTES_AND_NO_TX_ADVANCE",
    "R43C_06_DUPLICATE_ACK_REJECTED",
    "R43C_07_WRONG_ACK_FLAGS_0X00_DETECTED",
    "R43C_08_WRONG_ACK_FLAGS_DATA_DETECTED",
    "R43C_09_ACK_WITH_BODY_DETECTED",
    "R43C_10_WRONG_ACK_SEQUENCE_DETECTED",
    "R43C_11_WRONG_ACK_ACKNOWLEDGEMENT_DETECTED",
    "R43C_12_WRONG_ACK_CONNECTION_DETECTED",
    "R43C_13_LOCAL_CAPABILITIES_EMITTED",
    "R43C_14_SET_A_CAPABILITIES_EXACT_BYTES",
    "R43C_15_DUPLICATE_CAPABILITIES_REJECTED",
    "R43C_16_LOCAL_ALERTING_EMITTED",
    "R43C_17_ALERTING_EXACT_BYTES_AND_SEQUENCE_MODEL",
    "R43C_18_DUPLICATE_ALERTING_REJECTED",
    "R43C_19_PEER_CAPABILITIES_PARSED",
    "R43C_20_CAPABILITIES_SEEN",
    "R43C_21_CAPABILITIES_PARSE_OK",
    "R43C_22_CAPABILITIES_CALL_MATCH",
    "R43C_23_CAPABILITIES_VIDEO_REQUESTED",
    "R43C_24_PEER_DATA_ACK_EMITTED",
    "R43C_25_PEER_DATA_ACK_BEFORE_TRIGGER_NO_TX_ADVANCE",
    "R43C_26_MEDIA_OPEN_INTERCEPTED_ONE_OPEN",
    "R43C_27_DUPLICATE_PEER_CAPABILITIES_NO_SECOND_OPEN",
    "R43C_28_VIDEO_BIT_CLEAR_NO_OPEN",
    "R43C_29_WRONG_OPCODE_0X000C_REJECTED",
    "R43C_30_MALFORMED_CAPABILITIES_LENGTH_REJECTED",
    "R43C_31_FOREIGN_CONNECTION_REJECTED",
    "R43C_32_PRIOR_GENERATION_FRAME_REJECTED",
    "R43C_33_SEQUENCE_WRAP_CAPABILITIES_AT_0XFF",
    "R43C_34_SEQUENCE_WRAP_0XFF_TO_0X00_ACK_INDEPENDENT",
    "R43C_35_SET_B_RUNTIME_FIELDS_PARAMETERIZED",
    "R43C_36_SET_A_VALUES_NOT_HARDCODED",
)

FORBIDDEN_CORE_TOKENS = (
    "socket(",
    "sendto(",
    "connect(",
    "p12_queue_vip_frame(",
    "glib.h",
    "g_timeout_add",
    "printf(",
    "fprintf(",
    "open_door",
    "door_command",
    "relay",
    "SIGUSR1",
    "SIGUSR2",
)

FORBIDDEN_HARNESS_TOKENS = (
    "socket(",
    "sendto(",
    "<sys/socket.h>",
    "<netinet/in.h>",
    "open_door",
    "door_command",
    "gate_command",
    "SIGUSR1",
    "SIGUSR2",
    "system(",
    "popen(",
    "fork(",
)


def parse_markers(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if re.fullmatch(r"[A-Z0-9_]+", key):
            out[key] = value
    return out


class P116R43CCallAdoptionHostHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cc = shutil.which("cc")
        cls.harness_source = HARNESS.read_text(encoding="utf-8")
        cls.r45_source = Path(r45.__file__).read_text(encoding="utf-8")
        cls.production_source = PRODUCTION_TRANSFORM.read_text(encoding="utf-8")
        cls.compiled = False
        cls.compile_stderr = ""
        cls.harness_stdout = ""
        cls.harness_returncode: int | None = None
        cls.markers: dict[str, str] = {}

        if cls.cc:
            cls.tmp_obj = tempfile.TemporaryDirectory()
            cls.tmp = Path(cls.tmp_obj.name)
            combined = cls.tmp / "r43c_combined.c"
            combined.write_text(
                r35.CORE_REGION
                + "\n\n"
                + r36.CORE_REGION
                + "\n\n"
                + r45.CORE_REGION
                + "\n\n"
                + cls.harness_source,
                encoding="utf-8",
            )
            binary = cls.tmp / "r43c_harness"
            result = subprocess.run(
                [cls.cc or "cc", "-std=c99", "-Wall", "-Wextra", "-pedantic",
                 str(combined), "-o", str(binary)],
                text=True,
                capture_output=True,
            )
            cls.compile_stderr = result.stderr
            if result.returncode == 0:
                cls.compiled = True
                run = subprocess.run([str(binary)], text=True, capture_output=True)
                cls.harness_stdout = run.stdout
                cls.harness_returncode = run.returncode
                cls.markers = parse_markers(run.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmp_obj"):
            cls.tmp_obj.cleanup()

    def require_harness(self) -> None:
        if not self.compiled:
            self.skipTest(f"cc unavailable or compile failed: {self.compile_stderr}")

    # ---- harness execution -------------------------------------------------

    def test_harness_compiles_without_warnings(self) -> None:
        self.require_harness()
        self.assertEqual(self.compile_stderr.strip(), "", self.compile_stderr)

    def test_harness_runs_and_reports_pass(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        self.assertEqual(self.markers.get("R43C_HOST_HARNESS_RESULT"), "PASS")

    def test_all_scenario_markers_pass(self) -> None:
        self.require_harness()
        for key in SCENARIO_MARKERS:
            with self.subTest(key=key):
                self.assertEqual(self.markers.get(key), "PASS", f"{key} not PASS")

    def test_acceptance_pillars(self) -> None:
        self.require_harness()
        self.assertEqual(self.markers.get("R43C_05_INVITE_ACK_EXACT_BYTES_AND_NO_TX_ADVANCE"), "PASS")
        self.assertEqual(self.markers.get("R43C_14_SET_A_CAPABILITIES_EXACT_BYTES"), "PASS")
        self.assertEqual(self.markers.get("R43C_17_ALERTING_EXACT_BYTES_AND_SEQUENCE_MODEL"), "PASS")
        self.assertEqual(self.markers.get("R43C_25_PEER_DATA_ACK_BEFORE_TRIGGER_NO_TX_ADVANCE"), "PASS")
        self.assertEqual(self.markers.get("R43C_34_SEQUENCE_WRAP_0XFF_TO_0X00_ACK_INDEPENDENT"), "PASS")
        self.assertEqual(self.markers.get("R43C_35_SET_B_RUNTIME_FIELDS_PARAMETERIZED"), "PASS")
        self.assertEqual(self.markers.get("R43C_36_SET_A_VALUES_NOT_HARDCODED"), "PASS")

    def test_zero_real_side_effects(self) -> None:
        self.require_harness()
        self.assertEqual(self.markers.get("R43C_NETWORK_TX"), "0")
        self.assertEqual(self.markers.get("R43C_DOOR_ACTIONS"), "0")
        self.assertEqual(self.markers.get("R43C_GATE_ACTIONS"), "0")
        self.assertEqual(self.markers.get("R43C_SELF_ACTIVATION_ACTIONS"), "0")

    def test_peer_ack_precedes_trigger_in_source_order(self) -> None:
        src = self.harness_source
        self.assertLess(
            src.index("r45_accept_peer_data_and_ack"),
            src.index("r36_trigger_open_from_capabilities"),
        )

    # ---- hardcode / dependency discipline ---------------------------------

    def test_serializer_core_has_no_fixture_literals(self) -> None:
        core = r45.CORE_REGION
        self.assertNotIn("0x49", core)
        self.assertNotIn("0x27", core)
        self.assertNotIn("0x00000027", core)

    def test_core_is_dependency_free(self) -> None:
        core = r45.CORE_REGION
        for token in FORBIDDEN_CORE_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, core)

    def test_harness_has_no_network_or_actuator_primitive(self) -> None:
        for token in FORBIDDEN_HARNESS_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, self.harness_source)

    def test_primary_native_constants_pinned(self) -> None:
        core = r45.CORE_REGION
        self.assertIn("R45_CTP_FLAG_EMPTY_ACK        0x80u", core)
        self.assertIn("R45_OP_CAPABILITIES           0x0003u", core)
        self.assertIn("R45_OP_ALERTING               0x000Au", core)
        self.assertIn("R45_CAPABILITIES_BODY_LEN     8u", core)
        self.assertIn("R45_ALERTING_BODY_LEN         3u", core)

    # ---- current production gap (§9) --------------------------------------

    def test_production_transform_does_not_send_call_adoption_signaling(self) -> None:
        src = self.production_source
        for token in (
            "r45_send_invite_ack",
            "r45_send_local_capabilities",
            "r45_send_local_alerting",
            "CALL_INVITE_ACK",
            "CALL_CAPABILITIES",
            "CALL_ALERTING",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, src)

    def test_production_transform_still_waits_for_peer_capabilities(self) -> None:
        self.assertIn("r36_capabilities_video_requested", self.production_source)

    def test_production_component_tree_untouched_by_this_round(self) -> None:
        production = REPO_ROOT / "custom_components" / "comelit"
        self.assertTrue(production.is_dir())
        for path in production.rglob("*"):
            if path.is_file():
                self.assertNotIn("R43C", path.name)


if __name__ == "__main__":
    unittest.main()
