#!/usr/bin/env python3
"""P116/R46 offline replay tests for coalesced/fragmented post-UAut frames."""

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
HARNESS = Path(__file__).resolve().parent / "native" / "p116_r46_post_uaut_parser_replay_harness.c"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402
import entrance_p116_r36_attached_media_trigger_transform as r36  # noqa: E402
import entrance_p116_r45_call_adoption_core as r45  # noqa: E402


def parse_markers(stdout: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if re.fullmatch(r"[A-Z0-9_]+", key):
            markers[key] = value
    return markers


class P116R46PostUautParserReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cc = shutil.which("cc")
        cls.harness_source = HARNESS.read_text(encoding="utf-8")
        cls.compiled = False
        cls.compile_stderr = ""
        cls.stdout = ""
        cls.returncode: int | None = None
        cls.markers: dict[str, str] = {}

        if cls.cc:
            cls.tmp_obj = tempfile.TemporaryDirectory()
            cls.tmp = Path(cls.tmp_obj.name)
            combined = cls.tmp / "r46_combined.c"
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
            binary = cls.tmp / "r46_replay"
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
                cls.stdout = run.stdout
                cls.returncode = run.returncode
                cls.markers = parse_markers(run.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmp_obj"):
            cls.tmp_obj.cleanup()

    def require_harness(self) -> None:
        if not self.compiled:
            self.skipTest(f"cc unavailable or compile failed: {self.compile_stderr}")

    def test_compiles_warning_free(self) -> None:
        self.require_harness()
        self.assertEqual(self.compile_stderr.strip(), "", self.compile_stderr)

    def test_replay_suite_passes(self) -> None:
        self.require_harness()
        self.assertEqual(self.returncode, 0, self.stdout)
        self.assertEqual(self.markers.get("R46_PARSER_REPLAY_RESULT"), "PASS")

    def test_coalesced_frames_are_drained_in_one_replay(self) -> None:
        self.require_harness()
        self.assertEqual(
            self.markers.get("R46_COALESCED_CALL_INIT_AND_CAPABILITIES"),
            "PASS",
        )

    def test_fragmented_frames_wait_for_completion_then_resume(self) -> None:
        self.require_harness()
        self.assertEqual(
            self.markers.get("R46_FRAGMENTED_FRAME_REASSEMBLY"),
            "PASS",
        )

    def test_unrelated_channel_is_consumed_without_call_signaling(self) -> None:
        self.require_harness()
        self.assertEqual(
            self.markers.get("R46_UNRELATED_REQUEST_ID_NO_SIGNALING"),
            "PASS",
        )

    def test_malformed_outer_header_fails_closed(self) -> None:
        self.require_harness()
        self.assertEqual(
            self.markers.get("R46_MALFORMED_OUTER_HEADER_FAILS_CLOSED"),
            "PASS",
        )

    def test_duplicate_peer_capabilities_cannot_open_twice(self) -> None:
        self.require_harness()
        self.assertEqual(
            self.markers.get("R46_DUPLICATE_PEER_CAP_NO_SECOND_OPEN"),
            "PASS",
        )

    def test_replay_has_zero_real_side_effects(self) -> None:
        self.require_harness()
        self.assertEqual(self.markers.get("R46_NETWORK_TX"), "0")
        self.assertEqual(self.markers.get("R46_DOOR_ACTIONS"), "0")
        self.assertEqual(self.markers.get("R46_GATE_ACTIONS"), "0")

    def test_replay_source_keeps_consume_then_continue_contract(self) -> None:
        source = self.harness_source
        call_init = source.index("r45_send_invite_ack")
        consume = source.index("replay_consume(ctx, frame_len);", call_init)
        cont = source.index("continue;", consume)
        peer = source.index("r36_is_capabilities_for_current_call", cont)
        self.assertLess(call_init, consume)
        self.assertLess(consume, cont)
        self.assertLess(cont, peer)

    def test_peer_data_ack_precedes_media_trigger(self) -> None:
        source = self.harness_source
        guard = source.index("r36_is_capabilities_for_current_call")
        ack = source.index("r45_accept_peer_data_and_ack", guard)
        trigger = source.index("r36_trigger_open_from_capabilities", ack)
        self.assertLess(ack, trigger)


if __name__ == "__main__":
    unittest.main()
