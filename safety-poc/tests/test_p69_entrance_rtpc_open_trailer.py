from contextlib import redirect_stdout
from dataclasses import replace
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MEDIA = Path(__file__).resolve().parents[1] / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))
import entrance_rtpc_open_trailer_pcap_forensic as p69
from test_p68_entrance_rtpc_control_pairing import fixture, open_body


class P69TrailerTests(unittest.TestCase):
    def with_trailers(self, values):
        frames = fixture()
        for i, value in enumerate(values):
            frames[i] = replace(frames[i], body=frames[i].body[:14] + bytes([value]))
        return frames

    def test_observed_p68_symptoms_do_not_hide_structural_pairs(self):
        frames = self.with_trailers((1, 1, 1))  # Synthetic, not a capture value.
        old = p69.p68.analyze(frames)
        self.assertFalse(old.pairing_ok)
        self.assertEqual(old.typed_open_mismatches, ((14,), (14,)))
        self.assertTrue(all(p.matching_open_count == 0 for p in old.device_pairs + old.client_pairs))
        result = p69.analyze(frames)
        self.assertTrue(result.structural_pairing_ok)
        self.assertEqual(tuple(p.open_packet for p in result.pairs), (206, 205, 206))

    def test_all_scalar_values_are_observed_never_promoted_to_live_contract(self):
        for value in range(256):
            result = p69.analyze(self.with_trailers((value, value, value)))
            self.assertTrue(result.structural_pairing_ok)
            self.assertEqual(tuple(t.scalar for t in result.trailers), (value,) * 3)
            text = p69.report(result)
            self.assertIn("LIVE_BODY_GENERATION_CONTRACT=NOT_PROVEN", text)
            self.assertIn("OPEN_TRAILER_SEMANTICS=NOT_PROVEN", text)
            self.assertNotIn("LIVE_BODY_GENERATION_CONTRACT=PASS", text)

    def test_direction_dependent_trailers_are_not_hidden(self):
        result = p69.analyze(self.with_trailers((17, 23, 23)))
        self.assertTrue(result.structural_pairing_ok)
        self.assertTrue(result.client_trailers_equal)
        self.assertFalse(result.all_trailers_equal)
        self.assertEqual(tuple(t.scalar for t in result.trailers), (17, 23, 23))

    def test_malformed_envelope_still_fails(self):
        for index in (0, 1, 2):
            for offset in (0, 2, 4, 8):
                frames = self.with_trailers((17, 23, 23))
                body = bytearray(frames[index].body)
                body[offset] ^= 1
                frames[index] = replace(frames[index], body=bytes(body))
                self.assertFalse(p69.analyze(frames).structural_pairing_ok)

    def test_duplicates_missing_wrong_id_and_ambiguity_fail(self):
        frames = self.with_trailers((1, 1, 1))
        cases = [frames[1:], frames + [frames[0]],
                 frames[:5] + [replace(frames[5], body=frames[3].body)],
                 frames[:4] + [replace(frames[4], body=frames[3].body)] + frames[5:],
                 [replace(frames[0], first_packet=204, last_packet=204, timestamp=204.0)] + frames]
        for case in cases:
            self.assertFalse(p69.analyze(case).structural_pairing_ok)

    def test_unknown_channel_and_truncated_open_do_not_emit_scalar(self):
        for body in (open_body(0x5678, b"PRIV"), b"x" * 14):
            frames = fixture()
            frames[0] = replace(frames[0], body=body)
            result = p69.analyze(frames)
            self.assertFalse(result.structural_pairing_ok)
            self.assertEqual(len(result.trailers), 2)
            self.assertNotIn("PRIV", p69.report(result))

    def test_output_discloses_only_declared_scalar(self):
        text = p69.report(p69.analyze(self.with_trailers((17, 23, 23))))
        for value in ("1234", "1235", "5678", "4660", "4661", "22136", "3412", "7856"):
            self.assertNotIn(value, text)
        self.assertIn("unsigned_scalar=17", text)
        self.assertIn("unsigned_scalar=23", text)
        self.assertIn("CONTROL_TRAILER_SCALAR_EMITTED=true", text)
        self.assertIn("OTHER_CONTROL_BODY_VALUES_EMITTED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)

    def test_digest_gate_precedes_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.pcap"
            path.write_bytes(b"not-the-frozen-capture")
            with patch.object(p69.p68, "load_capture") as loader, redirect_stdout(io.StringIO()):
                self.assertEqual(p69.main(["--pcap", str(path)]), 2)
                loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
