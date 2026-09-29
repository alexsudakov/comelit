#!/usr/bin/env python3
"""P122 on-demand media Door offline contracts."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
REPO = ROOT.parent
STUB_INCLUDE = Path(__file__).resolve().parent / "native" / "whole_tu_stub_include"
sys.path.insert(0, str(MEDIA))

import entrance_p121_gather_initial_timeout_transform as p121  # noqa: E402
import entrance_p122_on_demand_media_door_transform as p122  # noqa: E402


class P122OnDemandMediaDoorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.p121_candidate = p121.transform(cls.source)
        cls.candidate_a = p122.transform(cls.source)
        cls.candidate_b = p122.transform(cls.source)
        cls.transport = (
            REPO / "custom_components" / "comelit" / "media_transport.py"
        ).read_text(encoding="utf-8")
        cls.button = (
            REPO / "custom_components" / "comelit" / "button.py"
        ).read_text(encoding="utf-8")
        cls.init_py = (
            REPO / "custom_components" / "comelit" / "__init__.py"
        ).read_text(encoding="utf-8")

    def test_transform_is_deterministic_and_composes_p121(self) -> None:
        self.assertEqual(self.candidate_a, self.candidate_b)
        self.assertIn("GATHER_INITIAL_TIMEOUT_SET_MS=250", self.candidate_a)
        self.assertIn("GATHER_INITIAL_TIMEOUT_RESTORED_MS=500", self.candidate_a)
        self.assertIn(p122.BEGIN, self.candidate_a)
        self.assertIn(p122.END, self.candidate_a)

    def test_active_media_profile_is_one_single_existing_ctpp_tx(self) -> None:
        c = self.candidate_a
        for needle in (
            "P122_TX_ONDEMAND_DOOR",
            "P122_ONDEMAND_DOOR_PATH=ACTIVE_MEDIA_SINGLE",
            "P122_ONDEMAND_DOOR_WRITE_COUNT=1",
            "P122_ONDEMAND_DOOR_EXISTING_CTPP_REUSED=true",
            "P122_ONDEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
            "P122_ONDEMAND_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
            "entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA",
            "p80_media_forwarding_enabled",
            "p78_rtpc_stage == P78_RTPC_COMPLETE",
            "!p12_tx_pending",
            "!r27_repeat_outstanding",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, c)

        region = c.split(p122.BEGIN, 1)[1].split(p122.END, 1)[0]
        self.assertNotIn("P12_TX_V4_OPEN_CTPP", region)
        self.assertNotIn("P12_TX_V4_OPEN_CSPB", region)
        self.assertNotIn("v4_door_queue_write", region)
        self.assertNotIn("V4_DOOR_TARGET_GATE", region)

    def test_serializer_matches_active_video_wire_shape(self) -> None:
        region = self.candidate_a.split(p122.BEGIN, 1)[1].split(p122.END, 1)[0]
        for needle in (
            "#define P122_DOOR_PACKET_LEN 48u",
            "p122_write_le16(out + 0, 0x1840u);",
            "p122_door_pending_sequence = previous_sequence + 0x00010000u;",
            "p122_write_le32(out + 2, p122_door_pending_sequence);",
            "p122_write_be16(out + 6, 0x000du);",
            "p122_write_be16(out + 8, 0x002du);",
            "memcpy(out + 10, V4_ENTRANCE, 8u);",
            "p122_write_le32(out + 20, P122_DOOR_RELAY_ENTRANCE);",
            "memset(out + 24, 0xff, 4u);",
            "memcpy(out + 28, V4_FULL_ADDRESS, 9u);",
            "memcpy(out + 38, V4_APT_ADDRESS, 8u);",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, region)

    def test_door_signal_is_media_helper_owned_and_one_shot(self) -> None:
        c = self.candidate_a
        self.assertIn("signal(SIGUSR1, p122_door_signal_handler);", c)
        self.assertIn("g_timeout_add(100u, p122_door_tick_cb, NULL)", c)
        self.assertIn("!p122_door_inflight", c)
        self.assertIn("p122_door_sent = TRUE;", c)
        self.assertIn(
            "if (p122_door_sent)\n        return p122_door_sequence;",
            c,
        )
        self.assertIn("r27_repeat_timer_cancelled = TRUE;", c)
        self.assertIn('p122_emit_result("REJECTED_NOT_READY")', c)
        self.assertIn('p122_emit_result("FAILED_SAFE")', c)
        self.assertIn('p122_emit_result("UNKNOWN_OUTCOME")', c)

    def test_manual_second_press_advances_from_last_committed_door_counter(self) -> None:
        region = self.candidate_a.split(p122.BEGIN, 1)[1].split(p122.END, 1)[0]
        self.assertIn(
            "p122_door_pending_sequence = previous_sequence + 0x00010000u;",
            region,
        )
        self.assertIn(
            "p122_door_sequence = p122_door_pending_sequence;",
            self.candidate_a,
        )
        self.assertIn(
            "if (p122_door_sent)\n        return p122_door_sequence;",
            region,
        )
        eligibility = region.split(
            "p122_door_eligible(void)", 1
        )[1].split("static gboolean\np122_serialize_door", 1)[0]
        self.assertIn("!p122_door_inflight", eligibility)
        self.assertNotIn("!p122_door_sent", eligibility)

        serializer = region.split(
            "p122_serialize_door", 1
        )[1].split("static void\np122_emit_result", 1)[0]
        self.assertNotIn(
            "p122_door_sequence = p122_door_pending_sequence;",
            serializer,
        )

        tx_case = self.candidate_a.split(
            "case P122_TX_ONDEMAND_DOOR:", 1
        )[1].split("break;", 1)[0]
        self.assertLess(
            tx_case.index(
                "p122_door_sequence = p122_door_pending_sequence;"
            ),
            tx_case.index("p122_door_sent = TRUE;"),
        )
        self.assertIn(
            "P122_ONDEMAND_DOOR_COUNTER_COMMITTED=true",
            tx_case,
        )
        self.assertIn(
            "P122_ONDEMAND_DOOR_SEQUENCE_AFTER=%u",
            tx_case,
        )

    def test_ack_is_observable_but_not_promoted_to_physical_proof(self) -> None:
        region = self.candidate_a.split(p122.BEGIN, 1)[1].split(p122.END, 1)[0]
        self.assertIn("prefix == 0x1800u && action == 0x0000u", region)
        self.assertIn("P122_ONDEMAND_DOOR_ACK_OBSERVED=%s", region)
        self.assertIn("P122_ONDEMAND_DOOR_RELAY_EVENT_OBSERVED=%s", region)
        self.assertIn("action == 0x0003u", region)
        self.assertIn("sub == 0x000eu", region)
        self.assertIn("P122_ONDEMAND_DOOR_PHYSICAL_EFFECT_ASSERTED=false", region)
        self.assertNotIn("physical_effect_asserted=true", region)

    def test_ha_dispatch_uses_active_media_owner_for_entrance_only(self) -> None:
        self.assertIn("async def async_open_door(", self.transport)
        self.assertIn("os.kill(process.pid, signal.SIGUSR1)", self.transport)
        self.assertIn('"path": "ON_DEMAND_MEDIA_SINGLE"', self.transport)
        self.assertIn('"one_shot_sequence_sent": one_shot_sent', self.transport)
        self.assertIn('"automatic_retry_allowed": False', self.transport)
        self.assertIn('"physical_effect_asserted": False', self.transport)

        self.assertIn("media_transport.active", self.button)
        self.assertIn("result = await transport.async_open_door()", self.button)
        self.assertIn('"ON_DEMAND_MEDIA_SINGLE"', self.button)

        self.assertIn("door == DOOR_ENTRANCE", self.init_py)
        self.assertIn("and media_transport.active", self.init_py)
        self.assertIn("return await media_transport.async_open_door(", self.init_py)

    def test_gate_is_still_fail_closed_while_media_owns_connection(self) -> None:
        gate = self.button.split("class ComelitGateDoorButton", 1)[1]
        self.assertIn("media_paused=self._supervisor.media_paused", gate)
        self.assertIn("if self._supervisor.media_paused:", gate)
        self.assertNotIn("async_open_door()", gate)

    def test_whole_generated_translation_unit_compiles(self) -> None:
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if not cc:
            self.skipTest("no C compiler available")
        with tempfile.TemporaryDirectory(prefix="p122-tu-") as tmp:
            tu = Path(tmp) / "p122-whole-tu.c"
            tu.write_text(self.candidate_a, encoding="utf-8")
            result = subprocess.run(
                [
                    cc,
                    "-std=gnu11",
                    "-fsyntax-only",
                    "-Wall",
                    "-Wextra",
                    "-Werror=implicit-function-declaration",
                    "-Werror=implicit-int",
                    "-I",
                    str(STUB_INCLUDE),
                    str(tu),
                ],
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr[:5000])


if __name__ == "__main__":
    unittest.main()
