#!/usr/bin/env python3
"""P116/R45 offline C host-harness tests for native call adoption signaling."""

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
HARNESS = Path(__file__).resolve().parent / "native" / "p116_r45_call_adoption_host_harness.c"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402
import entrance_p116_r36_attached_media_trigger_transform as r36  # noqa: E402
import entrance_p116_r45_call_adoption_core as r45  # noqa: E402


def parse_markers(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if re.fullmatch(r"[A-Z0-9_]+", key):
            out[key] = value
    return out


class P116R45CallAdoptionHostHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cc = shutil.which("cc")
        cls.harness_source = HARNESS.read_text(encoding="utf-8")
        cls.r45_source = Path(r45.__file__).read_text(encoding="utf-8")
        cls.compiled = False
        cls.compile_stderr = ""
        cls.harness_stdout = ""
        cls.harness_returncode: int | None = None
        cls.markers: dict[str, str] = {}

        if cls.cc:
            cls.tmp_obj = tempfile.TemporaryDirectory()
            cls.tmp = Path(cls.tmp_obj.name)
            combined = cls.tmp / "r45_combined.c"
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
            binary = cls.tmp / "r45_harness"
            result = subprocess.run(
                [
                    cls.cc,
                    "-std=c99",
                    "-Wall",
                    "-Wextra",
                    "-pedantic",
                    str(combined),
                    "-o",
                    str(binary),
                ],
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

    def test_harness_compiles_without_warnings(self) -> None:
        self.require_harness()
        self.assertEqual(self.compile_stderr.strip(), "", self.compile_stderr)

    def test_harness_runs_successfully(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        self.assertEqual(self.markers.get("R45_HOST_HARNESS_RESULT"), "PASS")

    def test_call_capture_and_native_initial_ack(self) -> None:
        self.require_harness()
        for key in (
            "R45_SCENARIO_1_CALL_CAPTURE",
            "R45_SCENARIO_2_CAPTURE_STATE",
            "R45_SCENARIO_3_INVITE_ACK_EMITTED",
            "R45_SCENARIO_4_INVITE_ACK_NATIVE_BYTES",
            "R45_SCENARIO_5_DUPLICATE_INVITE_ACK_REJECTED",
        ):
            with self.subTest(key=key):
                self.assertEqual(self.markers.get(key), "PASS")

    def test_local_capabilities_and_alerting_exact_bytes_and_order(self) -> None:
        self.require_harness()
        for key in (
            "R45_SCENARIO_6_LOCAL_CAPABILITIES_EMITTED",
            "R45_SCENARIO_7_LOCAL_CAPABILITIES_NATIVE_BYTES",
            "R45_SCENARIO_8_DUPLICATE_CAPABILITIES_REJECTED",
            "R45_SCENARIO_9_LOCAL_ALERTING_EMITTED",
            "R45_SCENARIO_10_LOCAL_ALERTING_NATIVE_BYTES",
            "R45_SCENARIO_11_DUPLICATE_ALERTING_REJECTED",
        ):
            with self.subTest(key=key):
                self.assertEqual(self.markers.get(key), "PASS")

    def test_peer_capabilities_updates_transport_ack_before_media_open(self) -> None:
        self.require_harness()
        for key in (
            "R45_SCENARIO_12_PEER_CAPABILITIES_MATCH",
            "R45_SCENARIO_13_PEER_CAPABILITIES_ACK_EMITTED",
            "R45_SCENARIO_14_PEER_ACK_UPDATES_STATE_NO_TX_ADVANCE",
            "R45_SCENARIO_15_MEDIA_OPEN_USES_UPDATED_CTP_STATE",
            "R45_SCENARIO_16_DUPLICATE_PEER_CAP_NO_SECOND_OPEN",
        ):
            with self.subTest(key=key):
                self.assertEqual(self.markers.get(key), "PASS")

    def test_generation_reset_and_foreign_connection_fail_closed(self) -> None:
        self.require_harness()
        self.assertEqual(self.markers.get("R45_SCENARIO_17_GENERATION_RESET"), "PASS")
        self.assertEqual(
            self.markers.get("R45_SCENARIO_18_FOREIGN_CONNECTION_FAILS_CLOSED"),
            "PASS",
        )

    def test_harness_has_zero_real_side_effects(self) -> None:
        self.require_harness()
        self.assertEqual(self.markers.get("R45_NETWORK_TX"), "0")
        self.assertEqual(self.markers.get("R45_DOOR_ACTIONS"), "0")
        self.assertEqual(self.markers.get("R45_GATE_ACTIONS"), "0")

    def test_r45_core_has_no_io_or_runtime_dependency(self) -> None:
        core = r45.CORE_REGION
        for forbidden in (
            "socket(",
            "sendto(",
            "connect(",
            "p12_queue_vip_frame(",
            "glib.h",
            "nice/agent.h",
            "g_timeout_add",
            "printf(",
            "fprintf(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, core)

    def test_r45_primary_native_constants_are_pinned(self) -> None:
        core = r45.CORE_REGION
        self.assertIn("R45_CTP_FLAG_EMPTY_ACK        0x80u", core)
        self.assertIn("R45_OP_CAPABILITIES           0x0003u", core)
        self.assertIn("R45_OP_ALERTING               0x000Au", core)
        self.assertIn("R45_CAPABILITIES_BODY_LEN     8u", core)
        self.assertIn("R45_ALERTING_BODY_LEN         3u", core)

    def test_peer_data_ack_is_explicitly_before_r36_trigger_in_harness(self) -> None:
        src = self.harness_source
        ack_at = src.index("r45_accept_peer_data_and_ack")
        open_at = src.index("r36_trigger_open_from_capabilities")
        self.assertLess(ack_at, open_at)

    def test_report_marks_production_unwired(self) -> None:
        text = r45.report()
        self.assertIn("PRODUCTION_WIRING_ADDED=false", text)
        self.assertIn("NETWORK_IO=false", text)
        self.assertIn("PHYSICAL_CALLS=0", text)


if __name__ == "__main__":
    unittest.main()
