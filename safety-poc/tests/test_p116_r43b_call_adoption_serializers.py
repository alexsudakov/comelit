"""P116/R43B call-adoption serializer contract tests (offline, no network).

Every expectation here is bound to a contract recovered from primary staged
native evidence on CT120 (static, read-only):

* empty transport ACK wire flags 0x80 (serializer ORs 0x80 for empty bodies);
* native outgoing acknowledgement byte = accepted peer sequence + 1;
* csp_send_capab_report body = 00 03 <call-type> <reserved=0> <word LE32>, len 8;
* csp_send_alerting body = 00 0a <runtime byte>, len 3 (not 0x000C / 8 bytes).
"""
from __future__ import annotations

from pathlib import Path
import inspect
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p116_r30_call_ctp_envelope_model import (  # noqa: E402
    FLAG_ACK,
    FLAG_DATA,
    parse_ctp_envelope,
)
from entrance_p116_r30b_call_transaction_model import (  # noqa: E402
    InboundPeerFacts,
    create_call_transaction,
)
import entrance_p116_r44_inbound_peer_simulator as sim  # noqa: E402
from entrance_p116_r44_inbound_peer_simulator import (  # noqa: E402
    LAB_LOCAL_ALERTING_BODY,
    LAB_LOCAL_CAPABILITIES_BODY,
    NATIVE_ALERTING_BODY_LENGTH,
    NATIVE_ALERTING_OPCODE,
    NATIVE_CAPABILITIES_BODY_LENGTH,
    NATIVE_CAPABILITIES_OPCODE,
    NATIVE_FIRST_ACK_FLAGS,
    R30B_ACK_BYTE_MODEL_MATCHES_NATIVE,
    STRICT_NATIVE_PROFILE,
    FakeInboundPanel,
    SimulationRejected,
    build_native_alerting_body,
    build_native_capabilities_body,
    build_lab_local_packet,
    parse_native_alerting_body,
    parse_native_capabilities_body,
    profile_ready,
    report,
    run_strict_native_call,
)


class P116R43BNativeSerializerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = FakeInboundPanel()
        self.invite = self.panel.build_invite()
        self.invite_env = parse_ctp_envelope(self.invite)

    # --- strict profile readiness -------------------------------------------
    def test_strict_profile_is_ready_and_primary_native(self) -> None:
        self.assertTrue(STRICT_NATIVE_PROFILE.primary_native)
        self.assertTrue(profile_ready(STRICT_NATIVE_PROFILE))
        self.assertTrue(sim.STRICT_NATIVE_PROFILE_READY)

    # --- A. exact transport ACK -------------------------------------------
    def test_strict_ack_exact_equality(self) -> None:
        ack = self.panel.build_native_local_ack()
        parsed = parse_ctp_envelope(ack)
        self.assertEqual(parsed.flags, NATIVE_FIRST_ACK_FLAGS)
        self.assertEqual(parsed.flags, 0x80)
        self.assertEqual(len(parsed.inner_body), 0)
        self.assertEqual(parsed.sequence, self.invite_env.acknowledgement)
        self.assertEqual(parsed.acknowledgement, (self.invite_env.sequence + 1) & 0xFF)
        self.assertEqual(parsed.connection, self.panel.local_connection)
        self.panel.observe_local_transport_ack(
            ack, profile=STRICT_NATIVE_PROFILE, strict_native=True
        )

    def test_r30b_ack_byte_model_matches_native(self) -> None:
        # The frozen R30A/R30B model (hash-pinned by the historical phase test)
        # still emits flags 0x00 and acknowledgement == peer_sequence.  Native
        # evidence refutes both: wire flags 0x80 and acknowledgement =
        # accepted peer sequence + 1.  The frozen model is deliberately NOT
        # rewritten; the mismatch is recorded here as the native contract.
        transaction = create_call_transaction(
            outer_ctpp_handle=7,
            serialized_ctp_packet=self.invite,
        )
        parsed = parse_ctp_envelope(self.invite)
        self.assertEqual(transaction.local_tx_sequence, parsed.acknowledgement)
        self.assertEqual(transaction.local_acknowledgement, parsed.sequence)

        ack_env = parse_ctp_envelope(sim_and_writer_ack(transaction)[0])
        self.assertEqual(ack_env.flags, FLAG_ACK)
        self.assertEqual(ack_env.acknowledgement, parsed.sequence)
        self.assertNotEqual(ack_env.flags, NATIVE_FIRST_ACK_FLAGS)
        self.assertNotEqual(ack_env.acknowledgement, (parsed.sequence + 1) & 0xFF)
        self.assertFalse(
            ack_env.flags == NATIVE_FIRST_ACK_FLAGS
            and ack_env.acknowledgement == (parsed.sequence + 1) & 0xFF
        )
        self.assertFalse(R30B_ACK_BYTE_MODEL_MATCHES_NATIVE)

    # --- B. exact CAPABILITIES --------------------------------------------
    def test_strict_capabilities_exact_equality(self) -> None:
        body = build_native_capabilities_body(call_type=0x49, capability_word=0x00000027)
        self.assertEqual(len(body), NATIVE_CAPABILITIES_BODY_LENGTH)
        self.assertEqual(body[0:2], b"\x00\x03")
        self.assertEqual(body[2], 0x49)
        self.assertEqual(body[3], 0x00)
        self.assertEqual(struct.unpack_from("<I", body, 4)[0], 0x27)
        self.assertEqual(parse_native_capabilities_body(body), (0x49, 0x00, 0x27))

        self.panel.observe_local_transport_ack(
            self.panel.build_native_local_ack(),
            profile=STRICT_NATIVE_PROFILE,
            strict_native=True,
        )
        packet = self.panel.build_native_local_capabilities(sequence=self.panel.local_body_sequence)
        envelope = parse_ctp_envelope(packet)
        self.assertEqual(envelope.flags, FLAG_DATA)
        self.assertEqual(envelope.opcode, NATIVE_CAPABILITIES_OPCODE)
        self.assertEqual(len(envelope.inner_body), NATIVE_CAPABILITIES_BODY_LENGTH)
        self.assertEqual(envelope.inner_body, body)
        self.panel.observe_local_capabilities(
            packet, profile=STRICT_NATIVE_PROFILE, strict_native=True
        )

    def test_capabilities_runtime_fields_are_formula_bound(self) -> None:
        other = build_native_capabilities_body(call_type=0x50, capability_word=0x0000033B)
        self.assertEqual(other[0:3], b"\x00\x03\x50")
        self.assertNotEqual(other, build_native_capabilities_body(call_type=0x49, capability_word=0x27))
        with self.assertRaises(ValueError):
            build_native_capabilities_body(call_type=0x100, capability_word=0)
        with self.assertRaises(ValueError):
            build_native_capabilities_body(call_type=0, capability_word=0x1_0000_0000)

    # --- C. exact ALERTING ------------------------------------------------
    def test_strict_alerting_exact_equality(self) -> None:
        body = build_native_alerting_body()
        self.assertEqual(body, b"\x00\x0a\x00")
        self.assertEqual(len(body), NATIVE_ALERTING_BODY_LENGTH)
        self.assertEqual(parse_native_alerting_body(body), 0x00)

        self.panel.observe_local_transport_ack(
            self.panel.build_native_local_ack(),
            profile=STRICT_NATIVE_PROFILE,
            strict_native=True,
        )
        self.panel.observe_local_capabilities(
            self.panel.build_native_local_capabilities(sequence=self.panel.local_body_sequence),
            profile=STRICT_NATIVE_PROFILE,
            strict_native=True,
        )
        packet = self.panel.build_native_local_alerting(sequence=self.panel.local_body_sequence)
        envelope = parse_ctp_envelope(packet)
        self.assertEqual(envelope.opcode, NATIVE_ALERTING_OPCODE)
        self.assertEqual(len(envelope.inner_body), NATIVE_ALERTING_BODY_LENGTH)
        self.assertEqual(envelope.inner_body, body)
        self.panel.observe_local_alerting(
            packet, profile=STRICT_NATIVE_PROFILE, strict_native=True
        )

    def test_native_alerting_refutes_public_setup_ack_shape(self) -> None:
        self.assertNotEqual(NATIVE_ALERTING_OPCODE, sim.OP_SETUP_ACK)
        self.assertEqual(NATIVE_ALERTING_BODY_LENGTH, 3)
        self.assertNotEqual(LAB_LOCAL_ALERTING_BODY, build_native_alerting_body())
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_transport_ack(
                self.panel.build_native_local_ack(), profile=STRICT_NATIVE_PROFILE, strict_native=True
            )
            self.panel.observe_local_capabilities(
                self.panel.build_native_local_capabilities(sequence=self.panel.local_body_sequence),
                profile=STRICT_NATIVE_PROFILE,
                strict_native=True,
            )
            self.panel.observe_local_alerting(
                build_lab_local_packet(
                    panel=self.panel,
                    sequence=self.panel.local_body_sequence or 0,
                    acknowledgement=self.invite_env.sequence,
                    body=LAB_LOCAL_ALERTING_BODY,
                ),
                profile=STRICT_NATIVE_PROFILE,
                strict_native=True,
            )

    # --- order ------------------------------------------------------------
    def test_exact_order_ack_capabilities_alerting(self) -> None:
        panel, frames = run_strict_native_call(panel=FakeInboundPanel())
        self.assertEqual(
            panel.safe_transcript(),
            (
                "PEER_INVITE_EMITTED",
                "LOCAL_TRANSPORT_ACK_ACCEPTED",
                "LOCAL_CAPABILITIES_ACCEPTED",
                "LOCAL_ALERTING_ACCEPTED",
            ),
        )
        self.assertLess(len(frames["ack"]), len(frames["capabilities"]))
        self.assertEqual(panel.generation, 1)

    def test_out_of_order_local_signaling_fails_closed(self) -> None:
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_capabilities(
                self.panel.build_native_local_capabilities(sequence=self.invite_env.acknowledgement),
                profile=STRICT_NATIVE_PROFILE,
                strict_native=True,
            )
        self.panel.observe_local_transport_ack(
            self.panel.build_native_local_ack(), profile=STRICT_NATIVE_PROFILE, strict_native=True
        )
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_alerting(
                self.panel.build_native_local_alerting(sequence=self.panel.local_body_sequence),
                profile=STRICT_NATIVE_PROFILE,
                strict_native=True,
            )

    # --- sequence advancement --------------------------------------------
    def test_sequence_advancement_rules(self) -> None:
        panel = FakeInboundPanel()
        panel.build_invite()
        first = panel.peer_acknowledgement
        panel.observe_local_transport_ack(
            panel.build_native_local_ack(), profile=STRICT_NATIVE_PROFILE, strict_native=True
        )
        self.assertEqual(panel.local_body_sequence, first)
        panel.observe_local_capabilities(
            panel.build_native_local_capabilities(sequence=first),
            profile=STRICT_NATIVE_PROFILE,
            strict_native=True,
        )
        self.assertEqual(panel.local_body_sequence, (first + 1) & 0xFF)
        panel.observe_local_alerting(
            panel.build_native_local_alerting(sequence=(first + 1) & 0xFF),
            profile=STRICT_NATIVE_PROFILE,
            strict_native=True,
        )
        self.assertEqual(panel.local_body_sequence, (first + 2) & 0xFF)

    # --- peer withholding -------------------------------------------------
    def test_peer_capabilities_withheld_until_local_signaling_complete(self) -> None:
        with self.assertRaises(SimulationRejected):
            self.panel.build_peer_capabilities()
        panel, _ = run_strict_native_call(panel=FakeInboundPanel())
        peer = parse_ctp_envelope(panel.build_peer_capabilities())
        self.assertEqual(peer.opcode, NATIVE_CAPABILITIES_OPCODE)
        self.assertTrue(peer.inner_body[4] & sim.CAP_VIDEO_REQUEST_BIT)

    # --- fail-closed on wrong bytes ---------------------------------------
    def test_wrong_flags_connection_sequence_body_fail_closed(self) -> None:
        wrong_flags = self.panel.build_native_local_ack()
        corrupted = bytearray(wrong_flags)
        corrupted[0] = 0x00
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_transport_ack(
                bytes(corrupted), profile=STRICT_NATIVE_PROFILE, strict_native=True
            )
        self.assertEqual(self.panel.events, ["PEER_INVITE_EMITTED"])

        wrong_connection = bytearray(self.panel.build_native_local_ack())
        wrong_connection[2] ^= 0x01
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_transport_ack(
                bytes(wrong_connection), profile=STRICT_NATIVE_PROFILE, strict_native=True
            )

        wrong_sequence = bytearray(self.panel.build_native_local_ack())
        wrong_sequence[4] = (wrong_sequence[4] + 1) % 256
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_transport_ack(
                bytes(wrong_sequence), profile=STRICT_NATIVE_PROFILE, strict_native=True
            )

        wrong_ack = bytearray(self.panel.build_native_local_ack())
        wrong_ack[5] = (wrong_ack[5] + 3) % 256
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_transport_ack(
                bytes(wrong_ack), profile=STRICT_NATIVE_PROFILE, strict_native=True
            )

        self.panel.observe_local_transport_ack(
            self.panel.build_native_local_ack(), profile=STRICT_NATIVE_PROFILE, strict_native=True
        )
        wrong_body = bytearray(
            self.panel.build_native_local_capabilities(sequence=self.panel.local_body_sequence)
        )
        wrong_body[-1] ^= 0xFF
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_capabilities(
                bytes(wrong_body), profile=STRICT_NATIVE_PROFILE, strict_native=True
            )

    def test_ack_with_body_is_rejected(self) -> None:
        packet = build_lab_local_packet(
            panel=self.panel,
            sequence=self.invite_env.acknowledgement,
            acknowledgement=(self.invite_env.sequence + 1) & 0xFF,
            body=b"\x00\x11body",
            flags=NATIVE_FIRST_ACK_FLAGS,
        )
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_transport_ack(
                packet, profile=STRICT_NATIVE_PROFILE, strict_native=True
            )

    # --- duplicates --------------------------------------------------------
    def test_duplicate_local_signaling_rejected(self) -> None:
        panel, frames = run_strict_native_call(panel=FakeInboundPanel())
        with self.assertRaises(SimulationRejected):
            panel.observe_local_capabilities(
                frames["capabilities"], profile=STRICT_NATIVE_PROFILE, strict_native=True
            )
        with self.assertRaises(SimulationRejected):
            panel.observe_local_alerting(
                frames["alerting"], profile=STRICT_NATIVE_PROFILE, strict_native=True
            )
        with self.assertRaises(SimulationRejected):
            panel.observe_local_transport_ack(
                frames["ack"], profile=STRICT_NATIVE_PROFILE, strict_native=True
            )

    # --- generation reset --------------------------------------------------
    def test_second_generation_resets_transaction_state(self) -> None:
        panel, _ = run_strict_native_call(panel=FakeInboundPanel())
        self.assertTrue(panel.local_alerting_seen)
        panel.begin_generation(2)
        self.assertFalse(panel.local_capabilities_seen)
        self.assertFalse(panel.local_alerting_seen)
        self.assertIsNone(panel.local_body_sequence)
        self.assertEqual(panel.safe_transcript(), ())

        panel.peer_connection = b"\x12\x35"
        panel.peer_sequence = 0x60
        panel.peer_acknowledgement = 0x11
        panel.build_invite()
        panel.observe_local_transport_ack(
            panel.build_native_local_ack(), profile=STRICT_NATIVE_PROFILE, strict_native=True
        )
        self.assertEqual(panel.local_body_sequence, 0x11)

    # --- LAB isolation ----------------------------------------------------
    def test_lab_constants_cannot_satisfy_strict_native(self) -> None:
        self.assertFalse(sim.LAB_CORROBORATION_PROFILE.primary_native)
        with self.assertRaises(sim.EvidenceGap):
            sim.LAB_CORROBORATION_PROFILE.require_strict_ready()
        panel = FakeInboundPanel()
        panel.build_invite()
        lab_ack = build_lab_local_packet(
            panel=panel,
            sequence=panel.peer_acknowledgement,
            acknowledgement=panel.peer_sequence,
            body=b"",
            flags=FLAG_ACK,
        )
        with self.assertRaises(SimulationRejected):
            panel.observe_local_transport_ack(
                lab_ack, profile=STRICT_NATIVE_PROFILE, strict_native=True
            )
        self.assertNotEqual(LAB_LOCAL_ALERTING_BODY, build_native_alerting_body())
        # Documented coincidence: the public CAPABILITIES fixture is byte-equal
        # to the native layout for its own runtime values, which proves nothing
        # about provenance; the ALERTING fixture is refuted outright.
        self.assertEqual(
            build_native_capabilities_body(call_type=0x49, capability_word=0x27),
            LAB_LOCAL_CAPABILITIES_BODY,
        )
        self.assertFalse(sim.LAB_CORROBORATION_PROFILE.primary_native)

    def test_lab_profile_still_works_for_lab_fixtures(self) -> None:
        panel = FakeInboundPanel()
        invite = panel.build_invite()
        invite_env = parse_ctp_envelope(invite)
        panel.observe_local_transport_ack(
            build_lab_local_packet(
                panel=panel,
                sequence=invite_env.acknowledgement,
                acknowledgement=invite_env.sequence,
                body=b"",
                flags=FLAG_ACK,
            ),
            profile=sim.LAB_CORROBORATION_PROFILE,
            strict_native=False,
        )
        panel.observe_local_capabilities(
            build_lab_local_packet(
                panel=panel,
                sequence=invite_env.acknowledgement,
                acknowledgement=invite_env.sequence,
                body=LAB_LOCAL_CAPABILITIES_BODY,
            ),
            profile=sim.LAB_CORROBORATION_PROFILE,
            strict_native=False,
        )
        panel.observe_local_alerting(
            build_lab_local_packet(
                panel=panel,
                sequence=(invite_env.acknowledgement + 1) & 0xFF,
                acknowledgement=invite_env.sequence,
                body=LAB_LOCAL_ALERTING_BODY,
            ),
            profile=sim.LAB_CORROBORATION_PROFILE,
            strict_native=False,
        )
        self.assertEqual(panel.safe_transcript()[-1], "LOCAL_ALERTING_ACCEPTED")

    # --- safety invariants -------------------------------------------------
    def test_no_network_no_door_no_gate_in_simulator_source(self) -> None:
        source = inspect.getsource(sim)
        for forbidden in ("socket", "urllib", "requests", "subprocess", "open("):
            self.assertNotIn(forbidden, source)
        for forbidden in ("door", "gate", "SIGUSR", "deploy", "restart"):
            self.assertNotIn(forbidden, source.lower())
        self.assertNotIn("socket", report())

    def test_report_marks_strict_ready_and_lab_isolated(self) -> None:
        text = report()
        self.assertIn("STRICT_NATIVE_PROFILE_READY=true", text)
        self.assertIn("STRICT_NATIVE_FAILS_CLOSED=false", text)
        self.assertIn("LAB_CONSTANTS_PROMOTABLE_TO_PRODUCTION=false", text)
        self.assertIn("LAB_CORROBORATION_STILL_ISOLATED=True", text)
        self.assertIn("NETWORK_IO=false", text)

    def test_native_flags_constant_is_bit7(self) -> None:
        self.assertEqual(NATIVE_FIRST_ACK_FLAGS, 0x80)
        self.assertNotEqual(NATIVE_FIRST_ACK_FLAGS, FLAG_ACK)


def sim_and_writer_ack(transaction):
    """Intercept the R30B transport ACK and return its serialized packet."""
    from entrance_p116_r30b_call_transaction_model import InterceptedWriter

    writer = InterceptedWriter()
    transaction.intercept_transport_ack(writer)
    return [record.serialized_ctp_packet for record in writer.writes]


class P116R43BR30BFactsTests(unittest.TestCase):
    def test_inbound_peer_facts_expose_sequence_and_ack_bytes(self) -> None:
        facts = InboundPeerFacts(
            outer_ctpp_handle=7,
            peer_connection_id=b"\x12\x34",
            peer_sequence=0x56,
            peer_acknowledgement=0x78,
            source_logical_address=b"00000643\x00\x00",
            destination_logical_address=b"000401177\x00",
            logical_call_id=b"LAB1",
        )
        packet = sim.FakeInboundPanel().build_invite()
        transaction = create_call_transaction(
            outer_ctpp_handle=facts.outer_ctpp_handle,
            serialized_ctp_packet=packet,
        )
        parsed = parse_ctp_envelope(packet)
        self.assertEqual(transaction.peer_sequence, parsed.sequence)
        self.assertEqual(transaction.peer_acknowledgement, parsed.acknowledgement)
        # Frozen-model semantics (kept as historical evidence, not native).
        self.assertEqual(transaction.next_tx_acknowledgement, parsed.sequence)
        self.assertEqual(transaction.local_tx_sequence, parsed.acknowledgement)


if __name__ == "__main__":
    unittest.main()
