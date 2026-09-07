from dataclasses import replace
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest

MEDIA = Path(__file__).resolve().parents[1] / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))
import entrance_rtpc_open_trailer_static_contract as p70
import entrance_rtpc_open_trailer_pcap_forensic as p69
from test_p68_entrance_rtpc_control_pairing import fixture


def p69_frames_with_trailers(values=(1, 1, 1)):
    """Synthetic P68-shaped frames with P69-style trailer scalars (never capture data)."""
    frames = fixture()
    for i, value in enumerate(values):
        frames[i] = replace(frames[i], body=frames[i].body[:14] + bytes([value]))
    return frames


class P70StaticContractTests(unittest.TestCase):
    def test_rtpc_contract_resolves_trailer_to_one(self):
        entry = p70.generation_contract(10)
        self.assertEqual(entry.key, 10)
        self.assertEqual(entry.tag, b"RTPC")
        self.assertEqual(entry.transport, 1)
        body = p70.serialize_open(entry.tag, target_id=0x1234, transport=entry.transport)
        self.assertEqual(len(body), 15)
        self.assertEqual(body[14], 1)

    def test_contract_is_scoped_to_rtpc_and_asserts_no_universal_trailer(self):
        self.assertFalse(p70.ALL_CHANNEL_OPEN_TRAILER_VALUE_ASSERTED)
        self.assertEqual(set(p70.CHANNEL_MAP_FACTS), {10})  # only the proven key is promoted
        with self.assertRaises(KeyError):
            p70.generation_contract(11)  # fail closed: no promoted evidence
        text = p70.report({}, None, None)
        self.assertIn("ALL_CHANNEL_OPEN_TRAILER_VALUE=NOT_ASSERTED", text)
        self.assertIn("ALL_CHANNEL_OPEN_TRAILER_VALUE_ASSERTED=false", text)
        self.assertNotIn("ALL_CHANNEL_OPEN_TRAILER_VALUE=1", text)

    def test_runtime_target_id_is_not_conflated_with_trailer(self):
        body_a = p70.serialize_open(b"RTPC", target_id=0x1234, transport=1)
        body_b = p70.serialize_open(b"RTPC", target_id=0x9ABC, transport=1)
        # bytes 12:14 little-endian carry the target id...
        self.assertEqual(body_a[12:14], bytes((0x34, 0x12)))
        self.assertEqual(body_b[12:14], bytes((0xBC, 0x9A)))
        # ...and byte 14 is the transport, independent of the id.
        self.assertEqual(body_a[14], 1)
        self.assertEqual(body_b[14], 1)
        self.assertEqual(body_a[14], body_b[14])
        text = p70.report({}, None, None)
        self.assertIn("RUNTIME_TARGET_ID_NOT_TRAILER=true", text)

    def test_channel_id_ten_is_not_treated_as_open_fourteen(self):
        entry = p70.generation_contract(10)  # lookup key 10 (Channel.id enum code)
        self.assertEqual(entry.key, 10)
        body = p70.serialize_open(entry.tag, target_id=0x1234, transport=entry.transport)
        # The enum lookup code 10 is the MAP KEY, never the serialized trailer.
        self.assertNotEqual(body[14], 10)
        self.assertEqual(body[14], 1)
        text = p70.report({}, None, None)
        self.assertIn("CHANNEL_ID_10_NOT_TRAILER=true", text)

    def test_p69_capture_observation_stays_consistent_with_static_contract(self):
        # P69 observed 1 for all three RTPC OPENs (frozen capture); the static
        # contract independently predicts 1. Consistency is corroboration only.
        self.assertTrue(p70.observed_consistent((1, 1, 1), expected_transport=1))
        self.assertFalse(p70.observed_consistent((1, 2, 1), expected_transport=1))
        self.assertFalse(p70.observed_consistent((), expected_transport=1))

    def test_p69_historical_output_is_preserved_as_not_proven(self):
        # History is not rewritten: the P69 analyzer still reports NOT_PROVEN...
        result = p69.analyze(p69_frames_with_trailers((1, 1, 1)))
        p69_text = p69.report(result)
        self.assertIn("OPEN_TRAILER_SEMANTICS=NOT_PROVEN", p69_text)
        self.assertIn("LIVE_BODY_GENERATION_CONTRACT=NOT_PROVEN", p69_text)
        # ...while the P70 promotion supersedes that status for RTPC only.
        p70_text = p70.report({}, None, None)
        self.assertIn("RTPC_OPEN_TRAILER_CONTRACT=PROVEN", p70_text)
        self.assertIn("P69_OPEN_TRAILER_SEMANTICS=HISTORICAL_NOT_PROVEN_PRESERVED", p70_text)

    def test_wrong_artifact_digest_fails_closed_before_any_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.bin"
            bad.write_bytes(b"x" * 64)
            for flag in ("--libvipcomelit-so", "--dex-classes7", "--dex-classes8", "--pcap"):
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(p70.main([flag, str(bad)]), 2)
                self.assertIn("_GATE=FAIL", out.getvalue())
                self.assertIn("NETWORK_IO_PERFORMED=false", out.getvalue())

    def test_missing_artifact_path_fails_closed(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(p70.main(["--libvipcomelit-so", "/nonexistent/so"]), 3)
        self.assertIn("STATIC_CONTRACT_GATE=FAIL", out.getvalue())

    def test_default_fixture_run_is_deterministic_and_complete(self):
        first = p70.report({}, None, None)
        second = p70.report({}, None, None)
        self.assertEqual(first, second)
        for marker in (
            "RTPC_OPEN_TRAILER_SEMANTICS=CHANNEL_TRANSPORT",
            "RTPC_OPEN_TRAILER_GENERATION_RULE=channel_map[RTPC].transport & 0xff",
            "RTPC_OPEN_TRAILER_VALUE=1",
            "RTPC_OPEN_TRAILER_CONTRACT=PROVEN",
            "LIVE_BODY_GENERATION_CONTRACT=PROVEN_STATIC",
            "LIVE_EXPERIMENT_REQUIRED=NO",
            "STATIC_BYTE_EVIDENCE=NOT_PROVIDED",
            "OBSERVED_RTPC_TRAILERS=NOT_PROVIDED",
            "PROPRIETARY_ARTIFACTS_COMMITTED=false",
        ):
            self.assertIn(marker, first)

    def test_output_leaks_no_payloads_or_secrets(self):
        text = p70.report({}, None, None)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("MEDIA_PAYLOAD_EMITTED=false", text)
        # No serialized body bytes, no hex dumps, no identifiers beyond the tag.
        body = p70.serialize_open(b"RTPC", target_id=0x1234, transport=1)
        self.assertNotIn(body.hex(), text)
        self.assertNotIn("cdab", text.lower())
        for value in ("1234", "4660", "22136"):
            self.assertNotIn(value, text)

    def test_default_cli_run_exits_zero_with_full_contract(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(p70.main([]), 0)
        self.assertIn("RTPC_OPEN_TRAILER_CONTRACT=PROVEN", out.getvalue())
        self.assertIn("NETWORK_IO_PERFORMED=false", out.getvalue())

    def test_serializer_model_rejects_invalid_input(self):
        with self.assertRaises(ValueError):
            p70.serialize_open(b"TOOLONG", 1, 1)      # tag must be exactly 4 bytes
        with self.assertRaises(ValueError):
            p70.serialize_open(b"RTPC", 0x10000, 1)    # target id out of range
        with self.assertRaises(ValueError):
            p70.serialize_open(b"RTPC", 1, 256)        # transport out of range


if __name__ == "__main__":
    unittest.main()
