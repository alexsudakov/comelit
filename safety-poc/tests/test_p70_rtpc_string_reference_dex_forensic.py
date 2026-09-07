from pathlib import Path
import sys
import unittest

MEDIA = Path(__file__).resolve().parents[1] / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import rtpc_string_reference_dex_forensic as p70


class P70DexReferenceTests(unittest.TestCase):
    def test_const_string_index_is_detected(self):
        units = [0x001A, 0x1234]
        self.assertEqual(p70.const_string_indices(units), (0x1234,))

    def test_const_string_jumbo_index_is_detected(self):
        units = [0x011B, 0x5678, 0x1234]
        self.assertEqual(p70.const_string_indices(units), (0x12345678,))

    def test_unrelated_instruction_does_not_create_reference(self):
        self.assertEqual(p70.const_string_indices([0x000E]), ())

    def test_two_string_references_preserve_order(self):
        units = [0x001A, 7, 0x000E, 0x011B, 8, 0]
        self.assertEqual(p70.const_string_indices(units), (7, 8))

    def test_truncated_const_string_fails_closed(self):
        with self.assertRaises(ValueError):
            p70.const_string_indices([0x001A])

    def test_truncated_jumbo_fails_closed(self):
        with self.assertRaises(ValueError):
            p70.const_string_indices([0x001B, 1])

    def test_parse_input_requires_digest(self):
        path, digest = p70.parse_input("/tmp/example.dex=" + "a" * 64)
        self.assertEqual(path, Path("/tmp/example.dex"))
        self.assertEqual(digest, "a" * 64)

    def test_report_contract_strings_are_public_safe(self):
        forbidden = (
            "RAW_PAYLOAD_EMITTED=true",
            "RAW_DEX_BYTES_EMITTED=true",
            "NETWORK_IO_PERFORMED=true",
            "DOOR_ACTION_SENT=true",
            "MEDIA_SIGNALING_SENT=true",
        )
        source = Path(p70.__file__).read_text(encoding="utf-8")
        for value in forbidden:
            self.assertNotIn(value, source)


if __name__ == "__main__":
    unittest.main()
