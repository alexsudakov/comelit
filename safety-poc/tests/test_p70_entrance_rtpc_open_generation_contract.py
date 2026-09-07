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

import entrance_rtpc_control_open_contract_pcap_forensic as p66
import entrance_rtpc_open_generation_contract as p70
import entrance_rtpc_open_trailer_pcap_forensic as p69


def id_relation(ordinal: int) -> p66.IdRelation:
    return p66.IdRelation(
        ordinal=ordinal,
        prior_control_match_count=0,
        device_same_order_match_count=1,
        device_reverse_order_match_count=0,
        device_same_order_positions=(8,),
        device_reverse_order_positions=(),
        wrapper_same_order_match_count=0,
        wrapper_reverse_order_match_count=0,
        wrapper_same_order_positions=(),
        wrapper_reverse_order_positions=(),
    )


def good_id_result() -> p66.Result:
    return p66.Result(
        open_count=2,
        fixed_field_contract=True,
        open_body_diff_positions=(12,),
        template_static_except_request_id=True,
        request_ids_distinct=True,
        request_ids_nonzero=True,
        request_ids_sequential=True,
        relations=(id_relation(1), id_relation(2)),
    )


def good_trailer_result() -> p69.Result:
    trailers = (
        p69.Trailer(205, "DEVICE_TO_CLIENT", 1, 1),
        p69.Trailer(206, "CLIENT_TO_DEVICE", 2, 1),
        p69.Trailer(206, "CLIENT_TO_DEVICE", 3, 1),
    )
    return p69.Result(
        control_count=6,
        open_count=3,
        trailers=trailers,
        pairs=(),
        client_trailers_equal=True,
        all_trailers_equal=True,
        client_ids_ok=True,
        peer_id_distinct=True,
        structural_pairing_ok=True,
    )


class P70RtpcOpenGenerationContractTests(unittest.TestCase):
    def test_composed_generation_contract_passes(self) -> None:
        result = p70.analyze(good_id_result(), good_trailer_result())
        self.assertTrue(result.structural_pairing_ok)
        self.assertTrue(result.runtime_id_generation_ok)
        self.assertTrue(result.runtime_ids_sequential)
        self.assertEqual(result.observed_rtpc_trailer_value, 1)
        self.assertTrue(result.independent_trailing_evidence_ok)
        self.assertTrue(result.independent_allocator_evidence_ok)
        self.assertTrue(result.trailer_generation_contract_ok)
        self.assertTrue(result.client_target_generation_contract_ok)
        self.assertTrue(result.open_body_generation_contract_ok)

        text = p70.report(result)
        self.assertIn("RTPC_OPEN_TRAILING_GENERATION_CONTRACT=PASS", text)
        self.assertIn("CLIENT_TARGET_GENERATION_CONTRACT=PASS", text)
        self.assertIn("RTPC_OPEN_BODY_GENERATION_CONTRACT=PASS", text)
        self.assertIn("OPEN_TRAILER_SEMANTICS=NOT_PROVEN", text)
        self.assertIn("LIVE_RUN_AUTHORIZED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)

    def test_observation_alone_cannot_promote_wrong_independent_value(self) -> None:
        evidence = replace(p70.DEFAULT_INDEPENDENT_EVIDENCE, rtpc_value=0)
        result = p70.analyze(good_id_result(), good_trailer_result(), evidence)
        self.assertFalse(result.independent_trailing_evidence_ok)
        self.assertFalse(result.trailer_generation_contract_ok)
        self.assertFalse(result.open_body_generation_contract_ok)

    def test_independent_evidence_alone_cannot_override_capture(self) -> None:
        trailer = good_trailer_result()
        changed = replace(
            trailer,
            trailers=tuple(replace(item, scalar=2) for item in trailer.trailers),
        )
        result = p70.analyze(good_id_result(), changed)
        self.assertEqual(result.observed_rtpc_trailer_value, 2)
        self.assertFalse(result.trailer_generation_contract_ok)
        self.assertFalse(result.open_body_generation_contract_ok)

    def test_mixed_capture_trailers_fail_closed(self) -> None:
        trailer = good_trailer_result()
        changed_trailers = list(trailer.trailers)
        changed_trailers[2] = replace(changed_trailers[2], scalar=2)
        changed = replace(
            trailer,
            trailers=tuple(changed_trailers),
            client_trailers_equal=False,
            all_trailers_equal=False,
        )
        result = p70.analyze(good_id_result(), changed)
        self.assertIsNone(result.observed_rtpc_trailer_value)
        self.assertFalse(result.trailer_generation_contract_ok)
        self.assertFalse(result.open_body_generation_contract_ok)

    def test_runtime_id_contract_is_required(self) -> None:
        ids = good_id_result()
        bad_relation = replace(ids.relations[1], device_same_order_match_count=0)
        changed = replace(ids, relations=(ids.relations[0], bad_relation))
        result = p70.analyze(changed, good_trailer_result())
        self.assertFalse(result.runtime_id_generation_ok)
        self.assertFalse(result.client_target_generation_contract_ok)
        self.assertFalse(result.open_body_generation_contract_ok)

    def test_sequential_relation_is_required_even_if_p66_base_property_passes(self) -> None:
        ids = replace(good_id_result(), request_ids_sequential=False)
        self.assertTrue(ids.runtime_generation_contract_ok)
        result = p70.analyze(ids, good_trailer_result())
        self.assertFalse(result.runtime_ids_sequential)
        self.assertFalse(result.client_target_generation_contract_ok)
        self.assertFalse(result.open_body_generation_contract_ok)

    def test_independent_allocator_must_be_local_and_sequential(self) -> None:
        evidence = replace(
            p70.DEFAULT_INDEPENDENT_EVIDENCE,
            sequential_local_allocator=False,
        )
        result = p70.analyze(good_id_result(), good_trailer_result(), evidence)
        self.assertFalse(result.independent_allocator_evidence_ok)
        self.assertFalse(result.client_target_generation_contract_ok)
        self.assertFalse(result.open_body_generation_contract_ok)

    def test_structural_pairing_remains_mandatory(self) -> None:
        trailer = replace(good_trailer_result(), structural_pairing_ok=False)
        result = p70.analyze(good_id_result(), trailer)
        self.assertFalse(result.trailer_generation_contract_ok)
        self.assertFalse(result.open_body_generation_contract_ok)

    def test_output_never_promotes_trailer_semantics_or_live_run(self) -> None:
        text = p70.report(p70.analyze(good_id_result(), good_trailer_result()))
        self.assertNotIn("OPEN_TRAILER_SEMANTICS=PASS", text)
        self.assertNotIn("LIVE_RUN_AUTHORIZED=true", text)
        self.assertIn("INDEPENDENT_EVIDENCE_FETCHED_AT_RUNTIME=false", text)
        self.assertIn("REQUEST_ID_VALUES_EMITTED=false", text)
        self.assertIn("OTHER_CONTROL_BODY_VALUES_EMITTED=false", text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("MEDIA_PAYLOAD_EMITTED=false", text)

    def test_digest_gate_precedes_capture_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.pcap"
            path.write_bytes(b"not-the-frozen-capture")
            with patch.object(p66, "load_capture") as loader, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(p70.main(["--pcap", str(path)]), 2)
                loader.assert_not_called()
            self.assertIn("PCAP_SHA256_GATE=FAIL", output.getvalue())
            self.assertIn("NETWORK_IO_PERFORMED=false", output.getvalue())


if __name__ == "__main__":
    unittest.main()
