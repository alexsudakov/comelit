from __future__ import annotations

import re
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
NATIVE_HELPER = ROOT.parent / "custom_components" / "comelit" / "native" / "comelit-media"
R32_DOC = MEDIA / "P116_R32_ATTACHED_INBOUND_MEDIA_EVIDENCE.md"

sys.path.insert(0, str(MEDIA))
from entrance_p116_r30_call_ctp_envelope_model import (  # noqa: E402
    FLAG_DATA,
    FLAG_SYN,
    OP_INVITE,
    OP_MEDIA_REQUEST,
    build_ctp_envelope,
    parse_ctp_envelope,
)
from entrance_p116_r30b_call_transaction_model import (  # noqa: E402
    InterceptedWriter,
    OuterCtppHandle,
    TransactionRejected,
    build_mediareq26_open,
    build_mediareq26_stop,
    create_call_transaction,
    run_offline_happy_path,
    verify_happy_path,
)


class P116R32CallBoundMediaEvidence(unittest.TestCase):
    def make_invite_packet(
        self,
        *,
        flags: int = FLAG_SYN,
        connection: bytes = b"\x12\x34",
        sequence: int = 0x56,
        acknowledgement: int = 0x78,
        opcode: int = OP_INVITE,
        body_len: int = 40,
    ) -> bytes:
        body = bytearray(body_len)
        if body_len >= 2:
            struct.pack_into(">H", body, 0, opcode)
        if body_len >= 22:
            body[2:12] = b"00000643\x00\x00"
            body[12:22] = b"000401177\x00"
        if body_len >= 28:
            body[24:28] = b"CALL"
        return build_ctp_envelope(
            flags=flags,
            connection=connection,
            sequence=sequence,
            acknowledgement=acknowledgement,
            inner_body=bytes(body),
            source_raw=b"00000643\x00\x00",
            destination_raw=b"000401177\x00",
        )

    def create_transaction_at_barrier(self):
        transaction = create_call_transaction(
            outer_ctpp_handle=OuterCtppHandle(7),
            serialized_ctp_packet=self.make_invite_packet(),
        )
        writer = InterceptedWriter()
        transaction.intercept_transport_ack(writer)
        transaction.intercept_capability_stage()
        transaction.intercept_alerting_stage()
        transaction.reach_call_signaling_order_barrier()
        return transaction, writer

    def test_call_ctp_id_is_captured_from_ctp_connection_not_outer_handle(self) -> None:
        transaction = create_call_transaction(
            outer_ctpp_handle=OuterCtppHandle(7),
            serialized_ctp_packet=self.make_invite_packet(connection=b"\x12\x34"),
        )
        self.assertEqual(transaction.peer_connection_id, b"\x12\x34")
        self.assertEqual(transaction.candidate_local_connection_id, b"\x92\x34")
        self.assertNotEqual(
            transaction.candidate_local_connection_id,
            struct.pack(">H", transaction.outer_ctpp_handle.value),
        )
        transaction.candidate_local_connection_id = transaction.outer_ctpp_handle  # type: ignore[assignment]
        with self.assertRaises(TypeError):
            transaction.connection_for_serialization()

    def test_initial_packet_fail_closed_for_truncated_wrong_version_non_syn_and_non_invite(self) -> None:
        with self.assertRaises(ValueError):
            create_call_transaction(
                outer_ctpp_handle=OuterCtppHandle(7),
                serialized_ctp_packet=b"\xc0\x18\x12",
            )
        wrong_version = bytearray(self.make_invite_packet())
        wrong_version[1] = 0x17
        with self.assertRaises(ValueError):
            create_call_transaction(
                outer_ctpp_handle=OuterCtppHandle(7),
                serialized_ctp_packet=bytes(wrong_version),
            )
        with self.assertRaises(TransactionRejected):
            create_call_transaction(
                outer_ctpp_handle=OuterCtppHandle(7),
                serialized_ctp_packet=self.make_invite_packet(flags=FLAG_DATA),
            )
        with self.assertRaises(TransactionRejected):
            create_call_transaction(
                outer_ctpp_handle=OuterCtppHandle(7),
                serialized_ctp_packet=self.make_invite_packet(opcode=OP_MEDIA_REQUEST),
            )

    def test_open_stop_contract_uses_full_ctp_packets_and_single_call_transaction(self) -> None:
        transaction, writer = run_offline_happy_path()
        evidence = verify_happy_path(transaction, writer)
        self.assertTrue(evidence["OPEN_USES_CALL_TRANSACTION_CONNECTION"])
        self.assertFalse(evidence["OPEN_USES_OUTER_CTPP_HANDLE_AS_CONNECTION"])
        self.assertTrue(evidence["STOP_USES_CALL_TRANSACTION_CONNECTION"])
        self.assertEqual(evidence["OPEN_INNER_MEDIAREQ26_LENGTH"], 26)
        self.assertEqual(evidence["OPEN_FULL_CTP_PACKET_LENGTH"], 60)
        self.assertEqual(evidence["STOP_INNER_MEDIAREQ26_LENGTH"], 26)
        self.assertEqual(evidence["STOP_FULL_CTP_PACKET_LENGTH"], 60)
        open_write = [w for w in writer.writes if w.semantic_kind == "MEDIA_OPEN"][0]
        stop_write = [w for w in writer.writes if w.semantic_kind == "MEDIA_STOP"][0]
        open_packet = parse_ctp_envelope(open_write.serialized_ctp_packet)
        stop_packet = parse_ctp_envelope(stop_write.serialized_ctp_packet)
        self.assertEqual(open_packet.inner_body[0:2], b"\x00\x11")
        self.assertEqual(stop_packet.inner_body[0:2], b"\x00\x11")
        self.assertEqual(open_packet.inner_body[2], 0x14)
        self.assertEqual(stop_packet.inner_body[2], 0x94)

    def test_open_stop_fail_closed_without_bound_call_and_correct_lifetime(self) -> None:
        transaction = create_call_transaction(
            outer_ctpp_handle=OuterCtppHandle(7),
            serialized_ctp_packet=self.make_invite_packet(),
        )
        writer = InterceptedWriter()
        with self.assertRaises(TransactionRejected):
            transaction.intercept_media_open(writer)
        transaction, writer = self.create_transaction_at_barrier()
        with self.assertRaises(TransactionRejected):
            transaction.intercept_media_stop(writer)
        transaction.allocate_media_channel(lambda: 0x3456)
        transaction.intercept_media_open(writer)
        with self.assertRaises(TransactionRejected):
            transaction.intercept_media_open(writer)
        with self.assertRaises(TransactionRejected):
            transaction.intercept_media_stop(writer, media_channel_id=0x3457)
        transaction.intercept_media_stop(writer)
        self.assertEqual(writer.network_writes, 0)
        self.assertEqual(writer.self_activation_actions, 0)
        self.assertEqual(writer.door_actions, 0)
        self.assertEqual(writer.gate_actions, 0)

    def test_mediareq26_body_layout_is_bounded_to_existing_offline_model(self) -> None:
        media_channel_id = 0x3456
        open_body = build_mediareq26_open(media_channel_id)
        stop_body = build_mediareq26_stop(media_channel_id)
        self.assertEqual(len(open_body), 26)
        self.assertEqual(len(stop_body), 26)
        self.assertEqual(open_body[0:2], b"\x00\x11")
        self.assertEqual(open_body[2], 0x14)
        self.assertEqual(open_body[3], 0x32)
        self.assertEqual(struct.unpack_from("<H", open_body, 8)[0], media_channel_id)
        self.assertEqual(struct.unpack_from("<H", open_body, 10)[0], 0xFFFF)
        self.assertEqual(struct.unpack_from("<H", open_body, 16)[0], 800)
        self.assertEqual(struct.unpack_from("<H", open_body, 18)[0], 480)
        self.assertEqual(struct.unpack_from("<H", open_body, 20)[0], 320)
        self.assertEqual(struct.unpack_from("<H", open_body, 22)[0], 240)
        self.assertEqual(open_body[24], 16)
        self.assertEqual(open_body[25], 0)
        self.assertEqual(stop_body[0:2], b"\x00\x11")
        self.assertEqual(stop_body[2], 0x94)
        self.assertEqual(stop_body[3], 0x00)
        self.assertEqual(struct.unpack_from("<H", stop_body, 8)[0], media_channel_id)
        self.assertEqual(stop_body[10:26], b"\x00" * 16)

    def test_helper_binary_has_no_native_media_channel_primitive_strings(self) -> None:
        strings = NATIVE_HELPER.read_bytes().decode("latin1", errors="ignore")
        self.assertIn("p76_build_client_001a", strings)
        self.assertIn("p80_media_forwarding_enabled", strings)
        self.assertIn("v4_ctpp_channel_id", strings)
        for forbidden in (
            "RtpDispatcher",
            "ViperTunnel",
            "openMediaRXChannel",
            "closeMediaRXChannel",
            "startVideoRX",
            "stopVideoRX",
            "viper_tunnel_channel_create",
        ):
            self.assertNotIn(forbidden, strings)

    def test_r32_document_required_markers_and_final_contract(self) -> None:
        text = R32_DOC.read_text(encoding="utf-8")
        expected = {
            "CALL_CTP_ID_SOURCE": "CTP_HEADER_CONNECTION_BYTES_2_3_DIRECTION_TRANSFORMED_NATIVE_CONN_ID",
            "CALL_CTP_ID_LIFETIME": "INBOUND_CALL_CTP_CONNECTION_OBJECT_CONN36_TO_CALLFSM_STORED_ID_UNTIL_CALL_TRANSACTION_CLOSE",
            "HELPER_CAN_CAPTURE_CALL_CTP_ID": "true",
            "MEDIAREQ26_OPEN_CONTRACT": "PARTIAL",
            "MEDIAREQ26_STOP_CONTRACT": "PARTIAL",
            "REGISTERED_CTPP_EQUIVALENT": "false",
            "MEDIA_RX_CHANNEL_OPEN_EQUIVALENT": "NO_EQUIVALENT",
            "MEDIA_RX_CHANNEL_CLOSE_EQUIVALENT": "NO_EQUIVALENT",
            "R29B_GAP_CLOSED": "false",
            "ATTACHED_PATH_NEW_ICE_EXPECTED": "0",
            "ATTACHED_PATH_NEW_CLOUD_EXPECTED": "0",
            "ATTACHED_PATH_NEW_PSEUDOTCP_EXPECTED": "0",
            "ATTACHED_PATH_NEW_REGISTRATION_EXPECTED": "0",
            "PRODUCTION_DESIGN_READY": "false",
            "PRODUCTION_FILES_CHANGED": "0",
            "LIVE_INVOCATIONS": "0",
            "NETWORK_TX": "0",
            "DOOR_ACTIONS": "0",
            "GATE_ACTIONS": "0",
            "DEPLOYS": "0",
            "HA_RESTARTS": "0",
            "RESULT": "BLOCKED_PRIMITIVE",
        }
        for key, value in expected.items():
            self.assertRegex(text, rf"(?m)^{re.escape(key)}={re.escape(value)}$")
        self.assertNotIn("PENDING_R32_RUN2", text)
        child4 = re.search(
            r"CHILD 4 - PRODUCTION DESIGN\n\n(?P<body>.*?)\n\nCHILD 5 - OBSERVABILITY PLAN",
            text,
            re.S,
        )
        child5 = re.search(
            r"CHILD 5 - OBSERVABILITY PLAN\n\n(?P<body>.*?)\n\n=== COMELIT P116 R32",
            text,
            re.S,
        )
        self.assertIsNotNone(child4)
        self.assertIsNotNone(child5)
        self.assertGreater(len(child4.group("body").strip()), 1000)
        self.assertGreater(len(child5.group("body").strip()), 1000)
        self.assertIn("DESIGN CANDIDATE - not proven", child4.group("body"))
        self.assertIn("This target flow is a production design candidate only", child4.group("body"))
        self.assertNotIn("This target flow is proven", child4.group("body"))
        self.assertIn("bootstrap_strategy", child4.group("body"))
        self.assertIn("ATTACHED_INBOUND_CALL", child4.group("body"))
        self.assertIn("SELF_ACTIVATION", child4.group("body"))
        self.assertIn("no new cloud negotiation", child4.group("body"))
        self.assertIn("one media owner", child4.group("body"))
        self.assertIn("MEDIA_RX_CHANNEL_OPEN_EQUIVALENT=NO_EQUIVALENT", text)
        self.assertIn("CALL_CTP_CAPTURED=true", child5.group("body"))
        self.assertIn("ICE_BOOTSTRAP_DELTA=0", child5.group("body"))
        self.assertIn("compound strings", child5.group("body"))
        self.assertIn("=== END COMELIT P116 R32 ATTACHED INBOUND MEDIA (REPO DOC) ===", text)
        self.assertNotIn("CLIENT_TX_ALLOWED=true:repeat", text)


if __name__ == "__main__":
    unittest.main()
