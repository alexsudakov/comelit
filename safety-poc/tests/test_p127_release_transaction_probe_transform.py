#!/usr/bin/env python3
"""Executable corrective coverage for the offline-only P127 overlay."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_p106_teardown_state_classification_transform as p106  # noqa: E402
import entrance_p116_r35_attached_media_native_transform as r35  # noqa: E402
import entrance_p116_r36_attached_media_trigger_transform as r36  # noqa: E402
import entrance_p116_r37_attached_media_live_readiness_transform as r37  # noqa: E402
import entrance_p127_release_transaction_probe_transform as p127  # noqa: E402


def envelope(
    inner: bytes,
    *,
    flags: int = p127.CTP_FLAG_DATA,
    version: int = p127.CTP_VERSION,
    connection: int = 0x8123,
    padding_byte: int = 0,
) -> bytes:
    padding = (-len(inner)) % 4
    return (
        bytes((flags, version))
        + connection.to_bytes(2, "big")
        + b"\x01\x02"
        + len(inner).to_bytes(2, "big")
        + inner
        + bytes((padding_byte,)) * padding
        + b"\xff" * 4
        + b"S" * 10
        + b"D" * 10
    )


class P127ReleaseProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = (
            ROOT / "research" / "door" / "v1_5_7" /
            "comelit-v4-persistent-ctpp-door.c"
        ).read_text(encoding="utf-8")
        cls.r37_candidate = r37.transform(
            r36.transform(r35.transform(p106.transform(source, include_p116=True)))
        )
        cls.candidate = p127.transform(cls.r37_candidate)

    def parse(self, packet: bytes, **kwargs):
        return p127.parse_release_envelope(
            packet,
            outer_channel=kwargs.get("outer_channel", 0x000A),
            expected_outer_channel=0x000A,
            expected_local_connection=0x0123,
        )

    def test_valid_release_accepts_different_inner_lengths(self) -> None:
        for inner in (b"\x00\x0e", b"\x00\x0e" + b"x" * 12, b"\x00\x0e" + b"y" * 17):
            parsed = self.parse(envelope(inner))
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed.inner_body, inner)

    def test_inner_len_fourteen_is_not_release_opcode(self) -> None:
        packet = envelope(b"\x12\x34" + b"x" * 12)
        self.assertEqual(packet[6:8], b"\x00\x0e")
        self.assertIsNone(self.parse(packet))

    def test_malformed_version_flags_length_padding_and_trailer_rejected(self) -> None:
        valid = envelope(b"\x00\x0eZ")
        cases = [
            envelope(b"\x00\x0e", version=0x17),
            envelope(b"\x00\x0e", flags=0x80),
            valid[:-1],
            envelope(b"\x00\x0eZ", padding_byte=1),
            valid[:-24] + b"\x00" + valid[-23:],
            envelope(b"\x00"),
        ]
        for packet in cases:
            self.assertIsNone(self.parse(packet))

    def test_foreign_channel_and_connection_rejected(self) -> None:
        self.assertIsNone(self.parse(envelope(b"\x00\x0e"), outer_channel=0x000B))
        self.assertIsNone(self.parse(envelope(b"\x00\x0e", connection=0x8456)))

    def test_retransmit_is_candidate_and_never_identity(self) -> None:
        previous = (0x000A, 0x8123, 100.0)
        self.assertEqual(
            p127.classify_repetition(
                previous, channel=0x000A, connection=0x8123, observed_at=115.0
            ),
            "RETRANSMIT_CANDIDATE",
        )
        self.assertEqual(
            p127.classify_repetition(
                previous, channel=0x000A, connection=0x8123, observed_at=115.001
            ),
            "UNKNOWN",
        )

    def test_generated_release_wiring_is_strictly_passive(self) -> None:
        wiring = self.candidate.split(p127.WIRING_BEGIN_MARKER, 1)[1].split(
            p127.WIRING_END_MARKER, 1
        )[0]
        for forbidden in (
            "r37_handle_remote_release(", "r35_send_stop(",
            "r35_teardown_call(", "p12_queue_vip_frame(",
            "p12_consume_post_ack(", "SHADOW_DECISION_EMIT",
        ):
            self.assertNotIn(forbidden, wiring)
        self.assertIn('p127_classification = "RETRANSMIT_CANDIDATE"', wiring)
        self.assertIn('printf("P127_CALL_IDENTITY=UNKNOWN', wiring)

    def test_reapplication_and_wrong_input_fail_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            p127.transform(self.candidate)
        with self.assertRaises(RuntimeError):
            p127.transform("not an R37 candidate")

    def test_native_c_parser_executes_positive_and_negative_cases(self) -> None:
        cc = shutil.which("cc")
        if cc is None:
            self.skipTest("cc unavailable")
        r35_core = r35.extract_core_region(self.r37_candidate)
        r37_core = r37.extract_core_region(self.r37_candidate)
        harness = r'''
#include <stdio.h>
int main(void) {
    unsigned char packet[36] = {
        0x40,0x18,0x81,0x23,0x01,0x02,0x00,0x02,0x00,0x0e,
        0x00,0x00,0xff,0xff,0xff,0xff,
        'S','S','S','S','S','S','S','S','S','S',
        'D','D','D','D','D','D','D','D','D','D'
    };
    R35AttachedMediaSession s = {0};
    R35CtpEnvelopeView view;
    s.outer_ctpp_handle = 0x000a;
    s.call_ctp_connection = 0x0123;
    if (!p127_is_passive_release(packet, sizeof packet, 0x000a, &s, &view)) return 1;
    packet[8] = 0x12;
    if (p127_is_passive_release(packet, sizeof packet, 0x000a, &s, &view)) return 2;
    packet[8] = 0x00;
    if (p127_is_passive_release(packet, sizeof packet, 0x000b, &s, &view)) return 3;
    puts("P127_NATIVE_C_PARSER=PASS");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "p127.c"
            binary = Path(tmp) / "p127"
            source.write_text(
                "#include <string.h>\n" + r35_core + "\n" + r37_core +
                "\n" + p127.CORE_REGION + "\n" + harness,
                encoding="utf-8",
            )
            compiled = subprocess.run(
                [cc, "-std=c99", str(source), "-o", str(binary)],
                text=True, capture_output=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(executed.returncode, 0, executed.stderr)
            self.assertEqual(executed.stdout.strip(), "P127_NATIVE_C_PARSER=PASS")

    def test_whole_generated_translation_unit_compiles(self) -> None:
        cc = shutil.which("cc")
        if cc is None:
            self.skipTest("cc unavailable")
        stub_include = Path(__file__).resolve().parent / "native" / "whole_tu_stub_include"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "p127-whole-tu.c"
            source.write_text(self.candidate, encoding="utf-8")
            compiled = subprocess.run(
                [
                    cc, "-std=c99", "-fsyntax-only", "-Wall", "-Wextra",
                    "-pedantic", "-I", str(stub_include), str(source),
                ],
                text=True, capture_output=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            self.assertEqual(compiled.stderr.strip(), "", compiled.stderr)


if __name__ == "__main__":
    unittest.main()
