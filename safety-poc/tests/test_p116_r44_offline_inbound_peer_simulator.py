from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p116_r30_call_ctp_envelope_model import (  # noqa: E402
    FLAG_ACK,
    FLAG_DATA,
    OP_INVITE,
    parse_ctp_envelope,
)
from entrance_p116_r44_inbound_peer_simulator import (  # noqa: E402
    CAP_VIDEO_REQUEST_BIT,
    EvidenceGap,
    FakeInboundPanel,
    LAB_CORROBORATION_PROFILE,
    LAB_LOCAL_ALERTING_BODY,
    LAB_LOCAL_CAPABILITIES_BODY,
    LAB_PEER_CAPABILITIES_BODY,
    OP_CAPABILITIES,
    OP_SETUP_ACK,
    STRICT_NATIVE_PROFILE,
    SimulationRejected,
    build_lab_local_packet,
    report,
)


class P116R44OfflineInboundPeerSimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = FakeInboundPanel()
        self.invite = self.panel.build_invite()
        self.invite_env = parse_ctp_envelope(self.invite)

    def _lab_ack(self) -> bytes:
        return build_lab_local_packet(
            panel=self.panel,
            sequence=self.invite_env.acknowledgement,
            acknowledgement=self.invite_env.sequence,
            body=b"",
            flags=FLAG_ACK,
        )

    def _lab_capabilities(self, sequence: int) -> bytes:
        return build_lab_local_packet(
            panel=self.panel,
            sequence=sequence,
            acknowledgement=self.invite_env.sequence,
            body=LAB_LOCAL_CAPABILITIES_BODY,
        )

    def _lab_alerting(self, sequence: int) -> bytes:
        return build_lab_local_packet(
            panel=self.panel,
            sequence=sequence,
            acknowledgement=self.invite_env.sequence,
            body=LAB_LOCAL_ALERTING_BODY,
        )

    def test_invite_fixture_matches_proven_envelope_shape(self) -> None:
        env = self.invite_env
        self.assertTrue(env.is_syn)
        self.assertEqual(env.opcode, OP_INVITE)
        self.assertEqual(len(env.inner_body), 40)
        self.assertEqual(env.connection, self.panel.peer_connection)
        self.assertEqual(env.sequence, self.panel.peer_sequence)
        self.assertEqual(env.acknowledgement, self.panel.peer_acknowledgement)

    def test_strict_native_profile_fails_closed_while_exact_bytes_missing(self) -> None:
        with self.assertRaises(EvidenceGap) as ctx:
            STRICT_NATIVE_PROFILE.require_strict_ready()
        msg = str(ctx.exception)
        self.assertIn("FIRST_ACK_FLAGS", msg)
        self.assertIn("CSP_SEND_CAPAB_REPORT_EXACT_BODY", msg)
        self.assertIn("CSP_SEND_ALERTING_EXACT_BODY", msg)

    def test_lab_profile_cannot_be_mistaken_for_primary_native(self) -> None:
        self.assertFalse(LAB_CORROBORATION_PROFILE.primary_native)
        with self.assertRaises(EvidenceGap):
            LAB_CORROBORATION_PROFILE.require_strict_ready()

    def test_full_lab_call_adoption_sequence_releases_peer_capabilities(self) -> None:
        ack = self._lab_ack()
        self.panel.observe_local_transport_ack(
            ack,
            profile=LAB_CORROBORATION_PROFILE,
            strict_native=False,
        )

        first_body_seq = self.invite_env.acknowledgement
        caps = self._lab_capabilities(first_body_seq)
        self.panel.observe_local_capabilities(
            caps,
            profile=LAB_CORROBORATION_PROFILE,
            strict_native=False,
        )

        alerting = self._lab_alerting((first_body_seq + 1) & 0xFF)
        self.panel.observe_local_alerting(
            alerting,
            profile=LAB_CORROBORATION_PROFILE,
            strict_native=False,
        )

        peer_caps = self.panel.build_peer_capabilities()
        env = parse_ctp_envelope(peer_caps)
        self.assertEqual(env.flags, FLAG_DATA)
        self.assertEqual(env.connection, self.panel.peer_connection)
        self.assertEqual(env.opcode, OP_CAPABILITIES)
        self.assertEqual(len(env.inner_body), 8)
        self.assertEqual(env.inner_body, LAB_PEER_CAPABILITIES_BODY)
        self.assertNotEqual(env.inner_body[4] & CAP_VIDEO_REQUEST_BIT, 0)
        self.assertEqual(
            self.panel.safe_transcript(),
            (
                "PEER_INVITE_EMITTED",
                "LOCAL_TRANSPORT_ACK_ACCEPTED",
                "LOCAL_CAPABILITIES_ACCEPTED",
                "LOCAL_ALERTING_ACCEPTED",
                "PEER_CAPABILITIES_EMITTED",
            ),
        )

    def test_peer_withholds_capabilities_until_local_signaling_is_complete(self) -> None:
        with self.assertRaises(SimulationRejected):
            self.panel.build_peer_capabilities()

        self.panel.observe_local_transport_ack(
            self._lab_ack(),
            profile=LAB_CORROBORATION_PROFILE,
            strict_native=False,
        )
        with self.assertRaises(SimulationRejected):
            self.panel.build_peer_capabilities()

        first_body_seq = self.invite_env.acknowledgement
        self.panel.observe_local_capabilities(
            self._lab_capabilities(first_body_seq),
            profile=LAB_CORROBORATION_PROFILE,
            strict_native=False,
        )
        with self.assertRaises(SimulationRejected):
            self.panel.build_peer_capabilities()

    def test_wrong_order_alerting_before_capabilities_rejected(self) -> None:
        self.panel.observe_local_transport_ack(
            self._lab_ack(),
            profile=LAB_CORROBORATION_PROFILE,
            strict_native=False,
        )
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_alerting(
                self._lab_alerting(self.invite_env.acknowledgement),
                profile=LAB_CORROBORATION_PROFILE,
                strict_native=False,
            )

    def test_wrong_call_connection_rejected(self) -> None:
        ack = bytearray(self._lab_ack())
        ack[2] ^= 0x01
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_transport_ack(
                bytes(ack),
                profile=LAB_CORROBORATION_PROFILE,
                strict_native=False,
            )

    def test_wrong_local_body_sequence_rejected(self) -> None:
        self.panel.observe_local_transport_ack(
            self._lab_ack(),
            profile=LAB_CORROBORATION_PROFILE,
            strict_native=False,
        )
        wrong_seq = (self.invite_env.acknowledgement + 7) & 0xFF
        with self.assertRaises(SimulationRejected):
            self.panel.observe_local_capabilities(
                self._lab_capabilities(wrong_seq),
                profile=LAB_CORROBORATION_PROFILE,
                strict_native=False,
            )

    def test_lab_body_shapes_are_bounded_and_explicit(self) -> None:
        self.assertEqual(len(LAB_LOCAL_CAPABILITIES_BODY), 8)
        self.assertEqual(LAB_LOCAL_CAPABILITIES_BODY[:2], b"\x00\x03")
        self.assertEqual(len(LAB_LOCAL_ALERTING_BODY), 8)
        self.assertEqual(LAB_LOCAL_ALERTING_BODY[:2], b"\x00\x0c")
        self.assertEqual(OP_SETUP_ACK, 0x000C)

    def test_safe_transcript_contains_no_raw_packets(self) -> None:
        transcript = self.panel.safe_transcript()
        self.assertTrue(all(isinstance(item, str) for item in transcript))
        self.assertFalse(any("00000643" in item for item in transcript))
        self.assertFalse(any("000401177" in item for item in transcript))

    def test_module_contract_declares_zero_side_effects(self) -> None:
        text = report()
        self.assertIn("NETWORK_IO=false", text)
        self.assertIn("PHYSICAL_CALLS=0", text)
        self.assertIn("STRICT_NATIVE_FAILS_CLOSED=true", text)
        self.assertIn("LAB_CONSTANTS_PROMOTABLE_TO_PRODUCTION=false", text)


if __name__ == "__main__":
    unittest.main()
