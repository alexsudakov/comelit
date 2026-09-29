#!/usr/bin/env python3
"""P122 on-demand media Door contract tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
STUB_INCLUDE = Path(__file__).resolve().parent / "native" / "whole_tu_stub_include"

sys.path.insert(0, str(MEDIA))

import entrance_p121_gather_initial_timeout_transform as p121  # noqa: E402
import entrance_p122_on_demand_door_transform as p122  # noqa: E402


def _reference_packet(
    counter: int,
    entrance: bytes = b"00000643",
    full_address: bytes = b"000401177",
    apt: bytes = b"00040117",
) -> bytes:
    out = bytearray(48)
    out[0:2] = b"\x40\x18"
    out[2:6] = counter.to_bytes(4, "little")
    out[6:8] = b"\x00\x0d"
    out[8:10] = b"\x00\x2d"
    out[10:20] = entrance.ljust(10, b"\x00")[:10]
    out[20:24] = (1).to_bytes(4, "little")
    out[24:28] = b"\xff\xff\xff\xff"
    out[28:38] = full_address.ljust(10, b"\x00")[:10]
    out[38:48] = apt.ljust(10, b"\x00")[:10]
    return bytes(out)


class P122OnDemandDoorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        cls.p121 = p121.transform(source, include_p116=True)
        cls.generated_a = p122.transform(source, include_p116=True)
        cls.generated_b = p122.transform(source, include_p116=True)

    def test_transform_is_deterministic_and_layered_on_p121(self) -> None:
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertNotEqual(
            hashlib.sha256(self.p121.encode()).hexdigest(),
            hashlib.sha256(self.generated_a.encode()).hexdigest(),
        )
        self.assertIn(p122.BEGIN, self.generated_a)
        self.assertIn(p122.END, self.generated_a)

    def test_active_media_door_is_single_existing_ctpp_tx(self) -> None:
        c = self.generated_a
        self.assertIn("P122_TX_ON_DEMAND_DOOR", c)
        self.assertIn("v4_ctpp_channel_id,", c)
        self.assertIn("P122_ON_DEMAND_DOOR_PATH=MEDIA_SESSION_SINGLE", c)
        self.assertIn("P122_ON_DEMAND_DOOR_WRITE_COUNT=1", c)
        self.assertIn("P122_ON_DEMAND_DOOR_EXISTING_CTPP_REUSED=true", c)
        self.assertNotIn("P122_TX_OPEN_CTPP", c)
        self.assertNotIn("P122_TX_OPEN_P2P", c)
        region = c.split(p122.BEGIN, 1)[1].split(p122.END, 1)[0]
        self.assertNotIn("P12_TX_V4_DOOR_WRITE", region)
        self.assertNotIn("V4_DOOR_TARGET_GATE", region)

    def test_eligibility_is_bound_to_active_on_demand_media(self) -> None:
        c = self.generated_a
        for needle in (
            "entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA",
            "p78_rtpc_stage == P78_RTPC_COMPLETE",
            "p80_media_forwarding_enabled",
            "pseudo_tcp",
            "pseudotcp_open",
            "!pseudotcp_graceful_stop_started",
            "v4_registered",
            "v4_ctpp_channel_id != 0u",
            "!p12_tx_pending",
            "!r27_repeat_outstanding",
            "!r27_refresh_fail_closed",
            "r27_initial_001a_sent_count == 1u",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, c)

    def test_wire_layout_matches_pcap_derived_active_video_profile(self) -> None:
        packet = _reference_packet(0x12345678)
        self.assertEqual(len(packet), 48)
        self.assertEqual(packet[:2], b"\x40\x18")
        self.assertEqual(packet[2:6], b"\x78\x56\x34\x12")
        self.assertEqual(packet[6:10], b"\x00\x0d\x00\x2d")
        self.assertEqual(packet[20:24], b"\x01\x00\x00\x00")
        self.assertEqual(packet[24:28], b"\xff\xff\xff\xff")
        self.assertEqual(packet[38:48], b"00040117\x00\x00")

        c = self.generated_a
        for needle in (
            "P122_DOOR_PACKET_LEN 48u",
            "write_le16(out + 0u, 0x1840u);",
            "write_le32(out + 2u, counter);",
            "out[7] = 0x0du;",
            "out[9] = 0x2du;",
            "p122_write_padded_ascii(out + 10u, V4_ENTRANCE, 10u);",
            "write_le32(out + 20u, 1u);",
            "memset(out + 24u, 0xff, 4u);",
            "p122_write_padded_ascii(out + 28u, V4_FULL_ADDRESS, 10u);",
            "p122_write_padded_ascii(out + 38u, V4_APT_ADDRESS, 10u);",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, c)

    def test_counter_uses_live_media_lineage_and_advances_refresh_baseline(self) -> None:
        c = self.generated_a
        self.assertIn("r27_repeat_001a_sequence", c)
        self.assertIn("r27_initial_001a_sequence", c)
        self.assertIn("next_counter = p122_next_media_counter(current_counter);", c)
        self.assertIn("p122_commit_counter_baseline()", c)
        self.assertIn(
            "write_le32(p78_rtpc_client_001a + 2u, p122_door_counter);", c
        )
        self.assertIn(
            "P122_ON_DEMAND_DOOR_COUNTER_BASELINE_ADVANCED=true", c
        )
        self.assertIn("P122_REFRESH_FAIL_CLOSED=true", c)

    def test_refresh_collision_is_deferred_not_concurrent(self) -> None:
        c = self.generated_a
        self.assertIn("if (p122_on_demand_door_busy())", c)
        self.assertIn("P122_REFRESH_DEFERRED_FOR_DOOR=true", c)
        self.assertIn("g_timeout_add_seconds(2u, r27_repeat_delay_cb, NULL)", c)

    def test_signal_handler_is_bounded_and_no_retry(self) -> None:
        c = self.generated_a
        self.assertIn("signal(SIGUSR1, p122_door_signal_handler);", c)
        self.assertIn("P122_ON_DEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false", c)
        region = c.split(p122.BEGIN, 1)[1].split(p122.END, 1)[0]
        handler = region.split("p122_door_signal_handler", 1)[1].split(
            "static gboolean", 1
        )[0]
        self.assertNotIn("printf(", handler)
        self.assertNotIn("p12_queue_vip_frame", handler)

    def test_whole_generated_translation_unit_compiles(self) -> None:
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if not cc:
            self.skipTest("no C compiler available")
        with tempfile.TemporaryDirectory(prefix="p122-tu-") as tmp:
            tu = Path(tmp) / "p122.c"
            tu.write_text(self.generated_a, encoding="utf-8")
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
