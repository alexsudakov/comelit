from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "research" / "media" / "v1" / "P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md"
TRANSFORM = ROOT / "research" / "media" / "v1" / "entrance_p116_r29_listener_attached_media_live_transform.py"


class P116R29AInboundMediaWireContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = DOC.read_text(encoding="utf-8")
        cls.transform = TRANSFORM.read_text(encoding="utf-8")

    def test_required_decision_tables_present(self) -> None:
        self.assertIn(
            "OPEN STEP | INITIATOR | INPUT STATE | OUTPUT STATE | WIRE ACTION | OUR EQUIVALENT | EVIDENCE",
            self.doc,
        )
        self.assertIn(
            "CLOSE STEP | INITIATOR | RESOURCE CLOSED | WIRE ACTION | PERSISTENT RESOURCE PRESERVED | OUR EQUIVALENT | EVIDENCE",
            self.doc,
        )
        for row in (
            "CALL_INIT",
            "call transaction creation",
            "HANDLE_MEDIAREQ",
            "media RX channel allocation",
            "RTPC OPEN/RESPONSE",
            "RTP forwarding enable",
            "first RTP",
            "video RX disable",
            "media RX channel close",
            "CTPP registration",
            "PseudoTCP",
            "process/listener",
        ):
            self.assertIn(row, self.doc)

    def test_open_model_remains_blocked_without_helper_generation(self) -> None:
        self.assertIn("INBOUND_MEDIA_OPEN_OWNERSHIP=CLIENT_INITIATED", self.doc)
        self.assertIn("R29_MEDIA_OPEN_MODEL=BLOCKED", self.doc)
        self.assertIn("R29_READY_FOR_ORIGINAL_LIVE=false", self.doc)
        self.assertIn("does not prove an executable call-bound inbound\nmapping", self.doc)
        self.assertIn("call-bound open emission", self.doc)
        self.assertNotIn("R29_MEDIA_OPEN_MODEL=PASS", self.doc)
        self.assertIn('printf("R29_MEDIA_OPEN_MODEL=BLOCKED\\n");', self.transform)

    def test_close_model_rederived_as_mediareq_stop_not_rtpc_close(self) -> None:
        self.assertIn(
            "MEDIA_CLOSE_WIRE_ACTION=CALL_BOUND_MEDIAREQ26_STOP_PLUS_LOCAL_MEDIA_DISPOSAL",
            self.doc,
        )
        self.assertRegex(
            self.doc,
            r"previous\s+`MEDIA_CLOSE_WIRE_ACTION=RTPC_CLOSE` label was imprecise",
        )
        self.assertIn("one call-bound `csp_send_mediareq26` stop", self.doc)
        self.assertRegex(self.doc, r"not a required standalone RTPC\s+close")
        self.assertIn("R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED", self.doc)
        self.assertNotIn("R29_MEDIA_ONLY_TEARDOWN_MODEL=PASS", self.doc)
        self.assertIn('printf("R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED\\n");', self.transform)

    def test_finding_summaries_confirm_and_refine_parent_hypotheses(self) -> None:
        expected = {
            "F1_CLOSE_PATH_WIRE_EMISSION=CONFIRMED_REFINED",
            "F2_DISPATCH_MODEL=REFUTED_AS_INDIRECT",
            "F3_OPEN_LOCAL_MODEL=CONFIRMED_WITH_WIRE_SPLIT",
            "F4_CLOSE_LOCAL_MODEL=PARTLY_REFUTED",
        }
        for marker in expected:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.doc)

    def test_zero_one_a_taxonomy_refines_gate_without_deleting_forbidden_forms(self) -> None:
        self.assertIn("## Explicit `0x1A` Taxonomy", self.doc)
        self.assertIn("ZERO_ONE_A_TAXONOMY_ROWS=6", self.doc)
        self.assertIn("self-activation `0x1A`", self.doc)
        self.assertIn("R27 repeat-loop `0x1A`", self.doc)
        self.assertIn("call-bound `mediareq26` open", self.doc)
        self.assertIn("call-bound `mediareq26` stop", self.doc)
        self.assertIn("SELF_ACTIVATION_SENT_COUNT=0", self.doc)
        self.assertIn("R27_REPEAT_SENT_COUNT=0", self.doc)
        self.assertIn("CALL_BOUND_MEDIAREQ26_SENT_COUNT", self.doc)
        self.assertIn("A self-activation emission or repeat-loop emission still fails the gate", self.doc)

    def test_csp_mediareq26_arg_model_and_dispatch_are_explicit(self) -> None:
        for marker in (
            "tail-dispatches directly to\n`ctp_write`",
            "CSP_MEDIAREQ26_ARG_MODEL=CALL_CTP_ID_PLUS_ACTION_FLAGS_ADDRESS_OR_CHANNEL_PORT_PAYLOAD_AND_MEDIA_PROFILE_FIELDS",
            "stored call CTP id",
            "address pointer unless the flags select the tunnel/channel form",
            "max RTP payload",
            "zeroed on close",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.doc)

    def test_on_channel_open_response_ordering_is_not_promoted_to_precondition(self) -> None:
        self.assertIn("ON_CHANNEL_OPEN_RES_PAIRING=RESPONSE_PAIRED_TO_LOCAL_CHANNEL_POINTER_STATUS", self.doc)
        self.assertIn("does not call or wait for\n`ViperTunnel::onChannelOpenRes`", self.doc)
        self.assertIn("not a precondition for native `mediareq26` emission", self.doc)
        self.assertIn("first RTP packet from the device is strictly after a peer channel-open response", self.doc)
        self.assertIn("pairs the response by the exact `viper_channel_str*`", self.doc)

    def test_rtpdispatcher_storage_requires_pointer_id_equivalent(self) -> None:
        self.assertIn(
            "RTPDISPATCHER_MEDIA_STATE_STORAGE=POINTER_AND_ID_STORED_IN_DISPATCHER_AFTER_TUNNEL_OPEN",
            self.doc,
        )
        self.assertIn("media RX channel pointer", self.doc)
        self.assertIn("media RX channel id", self.doc)
        self.assertIn("not just an RTP socket descriptor", self.doc)

    def test_mapping_declares_components_not_equivalence(self) -> None:
        self.assertIn("## Round 3 Helper-Local Mapping", self.doc)
        self.assertIn(
            "OFFICIAL PRIMITIVE | OUR HELPER PRIMITIVE | BINDING/SEMANTIC INPUTS | OWNERSHIP | MAPPING_STATUS | ANCHOR (helper file:function) | EVIDENCE",
            self.doc,
        )
        for marker in (
            "MAPPING_ROWS_TOTAL=6",
            "MAPPING_PROVEN_EQUIVALENT=0",
            "MAPPING_PROVEN_COMPONENT_ONLY=4",
            "MAPPING_NO_EQUIVALENT=1",
            "MAPPING_UNKNOWN=1",
            "ROW1_MEDIAREQ26_OPEN_EQUIVALENT=PROVEN_COMPONENT_ONLY",
            "ROW2_MEDIAREQ26_STOP_EQUIVALENT=NO_EQUIVALENT",
            "ROW3_CHANNEL_ALLOCATOR_EQUIVALENT=PROVEN_COMPONENT_ONLY",
            "ROW4_LOCAL_MEDIA_RX_STATE_EQUIVALENT=PROVEN_COMPONENT_ONLY",
            "ROW5_MEDIA_ONLY_DISPOSAL_EQUIVALENT=PROVEN_COMPONENT_ONLY",
            "ROW6_FIRST_RTP_DEPENDENCY=UNKNOWN_NOT_ON_CHANNEL_OPEN_RES_BEFORE_MEDIAREQ26_EMISSION",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.doc)
        self.assertIn("PROVEN_COMPONENT_ONLY", self.doc)
        self.assertIn("NO_EQUIVALENT", self.doc)
        self.assertIn("UNKNOWN", self.doc)
        self.assertIn("Queueing uses `v4_ctpp_channel_id`, not a stored inbound call CTP id", self.doc)
        self.assertIn("The allowed/forbidden distinction is trigger and binding", self.doc)
        self.assertIn("not the same 26-byte native helper buffer", self.doc)
        self.assertIn("OPEN_MAPPING_STATUS=UNKNOWN", self.doc)
        self.assertIn("CLOSE_MAPPING_STATUS=UNKNOWN", self.doc)

    def test_transform_forbidden_stubs_remain_scoped(self) -> None:
        self_region = self.transform[
            self.transform.index("R29_DISABLED_SELF_ACTIVATION_QUEUE"):
            self.transform.index("R29_DISABLED_CLIENT_001A_QUEUE")
        ]
        client_region = self.transform[
            self.transform.index("R29_DISABLED_CLIENT_001A_QUEUE"):
            self.transform.index("R29_READY_START_CB")
        ]
        attached_region = self.transform[
            self.transform.index("R29_FUNCTIONS"):
            self.transform.index("R29_DISABLED_SELF_ACTIVATION_QUEUE")
        ]
        self.assertIn("R29_SELF_ACTIVATION_DISABLED=true", self_region)
        self.assertIn("R29_CLIENT_001A_DISABLED=true", client_region)
        self.assertNotIn("P12_TX_ENTRANCE_SELF_ACTIVATION", self_region)
        self.assertNotIn("P78_TX_RTPC_CLIENT_001A", client_region)
        self.assertNotIn("pseudotcp_begin_graceful_stop", attached_region)

    def test_handle_mediareq_kept_distinct_from_client_mediareq(self) -> None:
        self.assertRegex(
            self.doc,
            r"`MEDIAREQ_RECEIVED` is therefore distinct from\s+`CLIENT_MEDIAREQ_SENT`",
        )
        self.assertIn("does not allocate media RX channels", self.doc)
        self.assertIn("never calls `openMediaRXChannel`", self.doc)

    def test_document_contains_no_absolute_native_addresses(self) -> None:
        allowed_protocol_values = {
            "SYNTHETIC_NON_SEMANTIC_TARGET_ID",
            "0x000A",
            "0x001A",
            "0x1100",
            "0x1840",
        }
        suspicious = {
            match.group(0)
            for match in re.finditer(r"\b0x[0-9a-fA-F]{4,}\b", self.doc)
            if match.group(0) not in allowed_protocol_values
        }
        self.assertEqual(set(), suspicious)
        self.assertNotIn("/root/comelit-static", self.doc)
        self.assertNotIn("Disassembly of section", self.doc)

    def test_no_phase_b_claim(self) -> None:
        self.assertIn("PHASE_B_IMPLEMENTED=false", self.doc)
        self.assertIn("No Phase B implementation is authorized", self.doc)
        self.assertIn("CASE D — both models BLOCKED", self.doc)
        self.assertIn("LIVE_RUN=NOT_RUN", self.doc)
        self.assertIn("PRODUCTION_FILES_CHANGED=0", self.doc)
        self.assertIn("NATIVE_PRODUCTION_BINARY_CHANGED=false", self.doc)

    def test_report_channel_shape_present(self) -> None:
        self.assertIn("## Observational Live Plan", self.doc)
        self.assertEqual(3, self.doc.count("MISSING_FACT="))
        self.assertEqual(3, self.doc.count("REQUIRED_OBSERVATION="))
        self.assertEqual(3, self.doc.count("DOOR_GATE=false"))
        self.assertEqual(3, self.doc.count("RING_BUDGET=ONE_INBOUND_CALL"))
        self.assertIn("CLIENT_TX_ALLOWED=false", self.doc)
        self.assertIn(
            "CLIENT_TX_ALLOWED=true:exactly one call-bound mediareq26 open on the stored inbound call transaction during the initial alerting transition",
            self.doc,
        )
        self.assertIn(
            "CLIENT_TX_ALLOWED=true:exactly one call-bound mediareq26 open on the stored inbound call transaction for the candidate media lane",
            self.doc,
        )
        self.assertIn("no self-activation, no repeat loop, no second call, no Door/Gate, no new registration", self.doc)
        self.assertIn("=== COMELIT P116 R29A REPORT (round 4) ===", self.doc)
        self.assertIn("=== END COMELIT P116 R29A REPORT (round 4) ===", self.doc)
        for key in (
            "OBSERVATIONAL_PLAN_BLOCKS=",
            "OBSERVATIONAL_CLIENT_TX_ALLOWED_VALUES=",
            "CASE_CLASSIFICATION=",
            "MAPPING_ROWS_TOTAL=",
            "ROW1_MEDIAREQ26_OPEN_EQUIVALENT=",
            "ROW2_MEDIAREQ26_STOP_EQUIVALENT=",
            "ROW6_FIRST_RTP_DEPENDENCY=",
            "GATE_REFINEMENT_IMPLEMENTED=",
            "PY_COMPILE=",
            "GENERATED_SOURCE_SHA256=",
            "MISSING_EVIDENCE=",
            "R29_READY_FOR_ORIGINAL_LIVE=",
        ):
            with self.subTest(key=key):
                self.assertIn(key, self.doc)


if __name__ == "__main__":
    unittest.main()
