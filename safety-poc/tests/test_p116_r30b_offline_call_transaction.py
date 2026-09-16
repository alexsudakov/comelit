from __future__ import annotations

from dataclasses import replace
import re
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
R29C_SOURCE = MEDIA / "entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py"
P76_SOURCE = MEDIA / "entrance_rtpc_control_media_runtime_transform.py"
MODEL_SOURCE = MEDIA / "entrance_p116_r30b_call_transaction_model.py"
TEST_SOURCE = Path(__file__)

sys.path.insert(0, str(MEDIA))
from entrance_p116_r30_call_ctp_envelope_model import (  # noqa: E402
    CTP_VERSION,
    FLAG_DATA,
    FLAG_SYN,
    OP_INVITE,
    OP_MEDIA_REQUEST,
    TRAILER_MARKER,
    build_ctp_envelope,
    parse_ctp_envelope,
)
from entrance_p116_r30b_call_transaction_model import (  # noqa: E402
    InterceptedWriter,
    MEDIA_CHANNEL_ALLOCATOR_STATUS,
    OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE,
    OuterCtppHandle,
    TransactionRejected,
    build_mediareq26_open,
    build_mediareq26_stop,
    create_call_transaction,
    derive_native_local_connection_id,
    report,
    run_offline_happy_path,
    verify_happy_path,
)


class P116R30BOfflineCallTransaction(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.r29c_source = R29C_SOURCE.read_text(encoding="utf-8")
        cls.p76_source = P76_SOURCE.read_text(encoding="utf-8")
        cls.model_source = MODEL_SOURCE.read_text(encoding="utf-8")
        cls.test_source = TEST_SOURCE.read_text(encoding="utf-8")

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

    def make_transaction(self, *, seed: int = 0x21):
        return create_call_transaction(
            outer_ctpp_handle=OuterCtppHandle(7),
            serialized_ctp_packet=self.make_invite_packet(),
            next_tx_sequence_seed=seed,
        )

    def advance_to_barrier(self, transaction, writer) -> None:
        transaction.intercept_transport_ack(writer)
        transaction.intercept_capability_stage()
        transaction.intercept_alerting_stage()
        transaction.reach_call_signaling_order_barrier()

    def test_a_happy_path_emits_required_marker_block_and_zero_live_actions(self) -> None:
        transaction, writer = run_offline_happy_path()
        marker_text = report()
        for marker in (
            "CALL_TRANSACTION_CAPTURE=PASS",
            "OUTER_CTPP_HANDLE_SEPARATION=PASS",
            "ACK_MODEL_INTERCEPTED=PASS",
            "CALL_SIGNALING_ORDER_BARRIER=PASS",
            "MEDIA_CHANNEL_SINGLE_ALLOCATION=PASS",
            "FULL_CTP_MEDIA_OPEN_SERIALIZATION=PASS",
            "FULL_CTP_MEDIA_STOP_SERIALIZATION=PASS",
            "OPEN_STOP_MEDIA_CHANNEL_IDENTITY=PASS",
            "PER_CALL_SEQUENCE_STATE=PASS",
            "INTERCEPTED_ACK_WRITES=1",
            "INTERCEPTED_MEDIA_OPEN_WRITES=1",
            "INTERCEPTED_MEDIA_STOP_WRITES=1",
            "NETWORK_WRITES=0",
            "DOOR_ACTIONS=0",
            "GATE_ACTIONS=0",
            "SELF_ACTIVATION_ACTIONS=0",
            "REFRESH_OR_REPEAT_ACTIONS=0",
            "PRODUCTION_FILES_CHANGED=0",
            "LOCAL_CONNECTION_DIRECTION_RULE=NATIVE_PROVEN",
            "OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=PROVEN",
            "LIVE_CALL_BOUND_MEDIA=NOT_PROVEN",
            "LIVE_AUTHORIZED=false",
        ):
            self.assertIn(marker, marker_text)
        self.assertEqual(
            transaction.events,
            [
                "INVITE_CAPTURED",
                "CALL_TRANSACTION_CREATED",
                "TRANSPORT_ACK_INTERCEPTED",
                "CAPABILITY_STAGE_INTERCEPTED",
                "ALERTING_STAGE_INTERCEPTED",
                "CALL_SIGNALING_ORDER_BARRIER_REACHED",
                "MEDIA_CHANNEL_ALLOCATED",
                "MEDIA_OPEN_INTERCEPTED",
                "MEDIA_STOP_INTERCEPTED",
            ],
        )
        self.assertEqual(writer.network_writes, 0)
        self.assertEqual(writer.door_actions, 0)
        self.assertEqual(writer.gate_actions, 0)
        self.assertEqual(writer.self_activation_actions, 0)
        self.assertEqual(writer.refresh_or_repeat_actions, 0)

    def test_negative_01_malformed_truncated_ctp_envelope_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create_call_transaction(
                outer_ctpp_handle=OuterCtppHandle(7),
                serialized_ctp_packet=b"\xc0\x18\x12",
                next_tx_sequence_seed=1,
            )
        length_mismatch = bytearray(self.make_invite_packet())
        struct.pack_into(">H", length_mismatch, 6, 39)
        with self.assertRaises(ValueError):
            create_call_transaction(
                outer_ctpp_handle=OuterCtppHandle(7),
                serialized_ctp_packet=bytes(length_mismatch),
                next_tx_sequence_seed=1,
            )
        bad_trailer = bytearray(self.make_invite_packet())
        bad_trailer[48:52] = b"\x00\x00\x00\x00"
        with self.assertRaises(ValueError):
            create_call_transaction(
                outer_ctpp_handle=OuterCtppHandle(7),
                serialized_ctp_packet=bytes(bad_trailer),
                next_tx_sequence_seed=1,
            )

    def test_negative_02_wrong_ctp_version_rejected(self) -> None:
        packet = bytearray(self.make_invite_packet())
        packet[1] = CTP_VERSION + 1
        with self.assertRaises(ValueError):
            create_call_transaction(
                outer_ctpp_handle=OuterCtppHandle(7),
                serialized_ctp_packet=bytes(packet),
                next_tx_sequence_seed=1,
            )

    def test_negative_03_non_syn_initial_packet_rejected(self) -> None:
        with self.assertRaises(TransactionRejected):
            create_call_transaction(
                outer_ctpp_handle=OuterCtppHandle(7),
                serialized_ctp_packet=self.make_invite_packet(flags=FLAG_DATA),
                next_tx_sequence_seed=1,
            )

    def test_negative_04_syn_with_non_invite_opcode_rejected(self) -> None:
        with self.assertRaises(TransactionRejected):
            create_call_transaction(
                outer_ctpp_handle=OuterCtppHandle(7),
                serialized_ctp_packet=self.make_invite_packet(opcode=OP_MEDIA_REQUEST),
                next_tx_sequence_seed=1,
            )

    def test_negative_05_outer_ctpp_handle_reused_as_call_connection_id_rejected(self) -> None:
        transaction = self.make_transaction()
        transaction.candidate_local_connection_id = transaction.outer_ctpp_handle  # type: ignore[assignment]
        with self.assertRaises(TypeError):
            transaction.connection_for_serialization()

    def test_negative_06_media_open_before_call_signaling_barrier_rejected(self) -> None:
        from entrance_p116_r30b_call_transaction_model import InterceptedWriter

        transaction = self.make_transaction()
        writer = InterceptedWriter()
        before = len(writer.writes)
        with self.assertRaises(TransactionRejected):
            transaction.intercept_media_open(writer)
        self.assertEqual(len(writer.writes), before)

    def test_negative_07_media_open_before_media_channel_allocation_rejected(self) -> None:
        from entrance_p116_r30b_call_transaction_model import InterceptedWriter

        transaction = self.make_transaction()
        writer = InterceptedWriter()
        self.advance_to_barrier(transaction, writer)
        before = len(writer.writes)
        with self.assertRaises(TransactionRejected):
            transaction.intercept_media_open(writer)
        self.assertEqual(len(writer.writes), before)

    def test_negative_08_zero_or_invalid_media_channel_id_rejected(self) -> None:
        from entrance_p116_r30b_call_transaction_model import InterceptedWriter

        for candidate in (0, 0x10000, "7"):
            transaction = self.make_transaction()
            writer = InterceptedWriter()
            self.advance_to_barrier(transaction, writer)
            before = len(writer.writes)
            with self.assertRaises(TransactionRejected):
                transaction.allocate_media_channel(lambda candidate=candidate: candidate)  # type: ignore[return-value]
            self.assertEqual(len(writer.writes), before)

    def test_negative_09_second_media_channel_allocation_rejected(self) -> None:
        from entrance_p116_r30b_call_transaction_model import InterceptedWriter

        transaction = self.make_transaction()
        writer = InterceptedWriter()
        self.advance_to_barrier(transaction, writer)
        transaction.allocate_media_channel(lambda: 0x3456)
        before = len(writer.writes)
        with self.assertRaises(TransactionRejected):
            transaction.allocate_media_channel(lambda: 0x3457)
        self.assertEqual(len(writer.writes), before)

    def test_negative_10_second_open_rejected(self) -> None:
        from entrance_p116_r30b_call_transaction_model import InterceptedWriter

        transaction = self.make_transaction()
        writer = InterceptedWriter()
        self.advance_to_barrier(transaction, writer)
        transaction.allocate_media_channel(lambda: 0x3456)
        transaction.intercept_media_open(writer)
        before = len(writer.writes)
        with self.assertRaises(TransactionRejected):
            transaction.intercept_media_open(writer)
        self.assertEqual(len(writer.writes), before)

    def test_negative_11_stop_before_open_rejected(self) -> None:
        from entrance_p116_r30b_call_transaction_model import InterceptedWriter

        transaction = self.make_transaction()
        writer = InterceptedWriter()
        self.advance_to_barrier(transaction, writer)
        transaction.allocate_media_channel(lambda: 0x3456)
        before = len(writer.writes)
        with self.assertRaises(TransactionRejected):
            transaction.intercept_media_stop(writer)
        self.assertEqual(len(writer.writes), before)

    def test_negative_12_stop_with_different_media_channel_id_rejected(self) -> None:
        from entrance_p116_r30b_call_transaction_model import InterceptedWriter

        transaction = self.make_transaction()
        writer = InterceptedWriter()
        self.advance_to_barrier(transaction, writer)
        transaction.allocate_media_channel(lambda: 0x3456)
        transaction.intercept_media_open(writer)
        before = len(writer.writes)
        with self.assertRaises(TransactionRejected):
            transaction.intercept_media_stop(writer, media_channel_id=0x3457)
        self.assertEqual(len(writer.writes), before)

    def test_negative_13_second_stop_creates_no_wire_action(self) -> None:
        from entrance_p116_r30b_call_transaction_model import InterceptedWriter

        transaction = self.make_transaction()
        writer = InterceptedWriter()
        self.advance_to_barrier(transaction, writer)
        transaction.allocate_media_channel(lambda: 0x3456)
        transaction.intercept_media_open(writer)
        transaction.intercept_media_stop(writer)
        before = len(writer.writes)
        with self.assertRaises(TransactionRejected):
            transaction.intercept_media_stop(writer)
        self.assertEqual(len(writer.writes), before)

    def test_negative_14_self_activation_or_repeat_path_fail_closed(self) -> None:
        writer = InterceptedWriter()
        for name in ("self_activation_actions", "refresh_or_repeat_actions"):
            with self.assertRaises((AttributeError, TypeError)):
                setattr(writer, name, 1)
        self.assertEqual(writer.self_activation_actions, 0)
        self.assertEqual(writer.refresh_or_repeat_actions, 0)
        self.assertEqual(writer.writes, [])

    def test_negative_15_network_writer_path_fail_closed_and_unincrementable(self) -> None:
        writer = InterceptedWriter()
        with self.assertRaises((AttributeError, TypeError)):
            writer.network_writes = 1  # type: ignore[misc]
        self.assertEqual(writer.network_writes, 0)
        self.assertEqual(writer.writes, [])
        self.assertNotIn("network_writes +=", self.model_source)

    def test_negative_16_door_and_gate_actions_fail_closed_and_unincrementable(self) -> None:
        writer = InterceptedWriter()
        for name in ("door_actions", "gate_actions"):
            with self.assertRaises((AttributeError, TypeError)):
                setattr(writer, name, 1)
        self.assertEqual(writer.door_actions, 0)
        self.assertEqual(writer.gate_actions, 0)
        self.assertEqual(writer.writes, [])
        self.assertNotIn("door_actions +=", self.model_source)
        self.assertNotIn("gate_actions +=", self.model_source)

    def test_structural_equivalence_open_and_stop_full_ctp_packets(self) -> None:
        transaction, writer = run_offline_happy_path()
        open_write = next(write for write in writer.writes if write.semantic_kind == "MEDIA_OPEN")
        stop_write = next(write for write in writer.writes if write.semantic_kind == "MEDIA_STOP")
        open_packet = parse_ctp_envelope(open_write.serialized_ctp_packet)
        stop_packet = parse_ctp_envelope(stop_write.serialized_ctp_packet)

        self.assertEqual(open_packet.flags, FLAG_DATA)
        self.assertEqual(open_packet.version, CTP_VERSION)
        self.assertEqual(open_packet.opcode, OP_MEDIA_REQUEST)
        self.assertEqual(len(open_packet.inner_body), 26)
        self.assertEqual(len(open_write.serialized_ctp_packet), 60)
        self.assertEqual(open_write.serialized_ctp_packet[36:40], TRAILER_MARKER)
        self.assertEqual(open_packet.connection, transaction.candidate_local_connection_id)
        self.assertNotEqual(open_packet.connection, struct.pack(">H", transaction.outer_ctpp_handle.value))
        self.assertEqual(struct.unpack_from("<H", open_packet.inner_body, 8)[0], transaction.media_channel_id)
        self.assertEqual(open_packet.source_raw, b"000401177\x00")
        self.assertEqual(open_packet.destination_raw, b"00000643\x00\x00")

        self.assertEqual(stop_packet.flags, FLAG_DATA)
        self.assertEqual(stop_packet.version, CTP_VERSION)
        self.assertEqual(stop_packet.opcode, OP_MEDIA_REQUEST)
        self.assertEqual(len(stop_packet.inner_body), 26)
        self.assertEqual(len(stop_write.serialized_ctp_packet), 60)
        self.assertEqual(stop_write.serialized_ctp_packet[36:40], TRAILER_MARKER)
        self.assertEqual(stop_packet.connection, open_packet.connection)
        self.assertEqual(struct.unpack_from("<H", stop_packet.inner_body, 8)[0], transaction.media_channel_id)
        self.assertEqual(stop_write.sequence, (open_write.sequence + 1) % 256)
        self.assertEqual(open_write.acknowledgement, stop_write.acknowledgement)
        self.assertEqual(open_packet.source_raw, stop_packet.source_raw)
        self.assertEqual(open_packet.destination_raw, stop_packet.destination_raw)

    def test_report_evidence_is_derived_from_parsed_intercepted_bytes(self) -> None:
        transaction, writer = run_offline_happy_path()
        evidence = verify_happy_path(transaction, writer)
        self.assertTrue(evidence["CALL_TRANSACTION_CAPTURE"])
        self.assertTrue(evidence["OUTER_CTPP_HANDLE_SEPARATION"])
        self.assertTrue(evidence["ACK_MODEL_INTERCEPTED"])
        self.assertTrue(evidence["CALL_SIGNALING_ORDER_BARRIER"])
        self.assertTrue(evidence["MEDIA_CHANNEL_SINGLE_ALLOCATION"])
        self.assertTrue(evidence["OPEN_MEDIA_CHANNEL_MATCH"])
        self.assertTrue(evidence["STOP_REUSES_OPEN_MEDIA_CHANNEL"])
        self.assertTrue(evidence["OUTBOUND_LOGICAL_ADDRESSES_REVERSED"])
        self.assertTrue(evidence["STOP_SEQUENCE_FOLLOWS_OPEN"])

        open_write = next(write for write in writer.writes if write.semantic_kind == "MEDIA_OPEN")
        corrupted_open = bytearray(open_write.serialized_ctp_packet)
        struct.pack_into("<H", corrupted_open, 16, 0x9999)
        open_corrupt_writer = InterceptedWriter(
            writes=[
                replace(
                    write,
                    serialized_ctp_packet=bytes(corrupted_open),
                )
                if write.semantic_kind == "MEDIA_OPEN"
                else write
                for write in writer.writes
            ]
        )
        open_corrupt_evidence = verify_happy_path(transaction, open_corrupt_writer)
        self.assertFalse(open_corrupt_evidence["OPEN_MEDIA_CHANNEL_MATCH"])
        self.assertFalse(open_corrupt_evidence["STOP_REUSES_OPEN_MEDIA_CHANNEL"])

        stop_write = next(write for write in writer.writes if write.semantic_kind == "MEDIA_STOP")
        corrupted_stop = bytearray(stop_write.serialized_ctp_packet)
        struct.pack_into("<H", corrupted_stop, 16, 0x9998)
        stop_corrupt_writer = InterceptedWriter(
            writes=[
                replace(
                    write,
                    serialized_ctp_packet=bytes(corrupted_stop),
                )
                if write.semantic_kind == "MEDIA_STOP"
                else write
                for write in writer.writes
            ]
        )
        stop_corrupt_evidence = verify_happy_path(transaction, stop_corrupt_writer)
        self.assertFalse(stop_corrupt_evidence["STOP_REUSES_OPEN_MEDIA_CHANNEL"])

        connection_corrupt = bytearray(open_write.serialized_ctp_packet)
        connection_corrupt[2:4] = b"\x00\x07"
        connection_corrupt_writer = InterceptedWriter(
            writes=[
                replace(write, serialized_ctp_packet=bytes(connection_corrupt))
                if write.semantic_kind == "MEDIA_OPEN"
                else write
                for write in writer.writes
            ]
        )
        connection_corrupt_evidence = verify_happy_path(transaction, connection_corrupt_writer)
        self.assertFalse(connection_corrupt_evidence["OPEN_USES_CALL_TRANSACTION_CONNECTION"])
        self.assertTrue(connection_corrupt_evidence["OPEN_USES_OUTER_CTPP_HANDLE_AS_CONNECTION"])
        self.assertFalse(connection_corrupt_evidence["OUTER_CTPP_HANDLE_SEPARATION"])

        barrier_corrupt_transaction = replace(
            transaction,
            events=[
                "INVITE_CAPTURED",
                "CALL_TRANSACTION_CREATED",
                "TRANSPORT_ACK_INTERCEPTED",
                "CALL_SIGNALING_ORDER_BARRIER_REACHED",
                "CAPABILITY_STAGE_INTERCEPTED",
                "ALERTING_STAGE_INTERCEPTED",
                "MEDIA_CHANNEL_ALLOCATED",
                "MEDIA_OPEN_INTERCEPTED",
                "MEDIA_STOP_INTERCEPTED",
            ],
        )
        barrier_corrupt_evidence = verify_happy_path(barrier_corrupt_transaction, writer)
        self.assertFalse(barrier_corrupt_evidence["CALL_SIGNALING_ORDER_BARRIER"])

    def test_native_adopted_state_comes_from_inbound_sequence_and_ack_bytes(self) -> None:
        packet = self.make_invite_packet(sequence=0xA6, acknowledgement=0x3C)
        transaction = create_call_transaction(
            outer_ctpp_handle=OuterCtppHandle(7),
            serialized_ctp_packet=packet,
            next_tx_sequence_seed=0x00,
        )
        same_transaction = create_call_transaction(
            outer_ctpp_handle=OuterCtppHandle(7),
            serialized_ctp_packet=packet,
            next_tx_sequence_seed=0xFF,
        )
        parsed = parse_ctp_envelope(packet)
        self.assertEqual(transaction.local_tx_sequence, parsed.acknowledgement)
        self.assertEqual(transaction.local_acknowledgement, parsed.sequence)
        self.assertEqual(same_transaction.local_tx_sequence, transaction.local_tx_sequence)
        self.assertEqual(same_transaction.local_acknowledgement, transaction.local_acknowledgement)

        corrupted = bytearray(packet)
        corrupted[5] ^= 0x01
        corrupted_transaction = create_call_transaction(
            outer_ctpp_handle=OuterCtppHandle(7),
            serialized_ctp_packet=bytes(corrupted),
            next_tx_sequence_seed=0x00,
        )
        self.assertFalse(
            corrupted_transaction.local_tx_sequence == parsed.acknowledgement
            and corrupted_transaction.local_acknowledgement == parsed.sequence
        )

    def test_sequence_wrap_does_not_carry_into_acknowledgement(self) -> None:
        transaction = self.make_transaction(seed=0x01)
        transaction.next_tx_sequence = 0xFF
        transaction.next_tx_acknowledgement = 0x44
        writer = InterceptedWriter()
        self.advance_to_barrier(transaction, writer)
        transaction.allocate_media_channel(lambda: 0x3456)
        open_write = transaction.intercept_media_open(writer)
        open_packet = parse_ctp_envelope(open_write.serialized_ctp_packet)
        self.assertEqual(open_packet.sequence, 0xFF)
        self.assertEqual(open_packet.acknowledgement, 0x44)
        self.assertEqual(transaction.local_tx_sequence, 0x00)
        self.assertEqual(transaction.local_acknowledgement, 0x44)

        corrupted = bytearray(open_write.serialized_ctp_packet)
        corrupted[5] ^= 0x01
        corrupted_packet = parse_ctp_envelope(bytes(corrupted))
        self.assertFalse(
            corrupted_packet.sequence == 0xFF and corrupted_packet.acknowledgement == 0x44
        )

    def test_peer_sequence_wrap_updates_ack_without_advancing_local_sequence(self) -> None:
        transaction = create_call_transaction(
            outer_ctpp_handle=OuterCtppHandle(7),
            serialized_ctp_packet=self.make_invite_packet(sequence=0xFF, acknowledgement=0x22),
        )
        before_tx_sequence = transaction.local_tx_sequence
        body_packet = build_ctp_envelope(
            flags=FLAG_DATA,
            connection=transaction.peer_connection_id,
            sequence=0xFF,
            acknowledgement=0x00,
            inner_body=b"\x00\x11body",
            source_raw=transaction.destination_logical_address,
            destination_raw=transaction.source_logical_address,
        )
        transaction.accept_inbound_body_packet(body_packet)
        self.assertEqual(transaction.local_acknowledgement, 0x00)
        self.assertEqual(transaction.local_tx_sequence, before_tx_sequence)

        corrupted = bytearray(body_packet)
        corrupted[4] = 0xFE
        with self.assertRaises(TransactionRejected):
            transaction.accept_inbound_body_packet(bytes(corrupted))

    def test_empty_ack_does_not_advance_local_tx_sequence(self) -> None:
        transaction = self.make_transaction(seed=0x01)
        before = transaction.local_tx_sequence
        writer = InterceptedWriter()
        ack_write = transaction.intercept_transport_ack(writer)
        ack_packet = parse_ctp_envelope(ack_write.serialized_ctp_packet)
        self.assertEqual(len(ack_packet.inner_body), 0)
        self.assertEqual(transaction.local_tx_sequence, before)

        corrupted = bytearray(ack_write.serialized_ctp_packet)
        corrupted[4] = (corrupted[4] + 1) % 256
        corrupted_packet = parse_ctp_envelope(bytes(corrupted))
        self.assertFalse(corrupted_packet.sequence == before)

    def test_native_connection_transform_does_not_mutate_sequence_or_acknowledgement(self) -> None:
        packet = self.make_invite_packet(connection=b"\x12\x34", sequence=0xB1, acknowledgement=0xC2)
        transaction = create_call_transaction(
            outer_ctpp_handle=OuterCtppHandle(7),
            serialized_ctp_packet=packet,
        )
        parsed = parse_ctp_envelope(packet)
        self.assertEqual(transaction.candidate_local_connection_id, b"\x92\x34")
        self.assertEqual(transaction.local_tx_sequence, parsed.acknowledgement)
        self.assertEqual(transaction.local_acknowledgement, parsed.sequence)

        corrupted = self.make_invite_packet(connection=b"\x12\x35", sequence=0xB1, acknowledgement=0xC2)
        corrupted_transaction = create_call_transaction(
            outer_ctpp_handle=OuterCtppHandle(7),
            serialized_ctp_packet=corrupted,
        )
        self.assertNotEqual(corrupted_transaction.candidate_local_connection_id, transaction.candidate_local_connection_id)
        self.assertEqual(corrupted_transaction.local_tx_sequence, transaction.local_tx_sequence)
        self.assertEqual(corrupted_transaction.local_acknowledgement, transaction.local_acknowledgement)

    def test_native_derived_local_connection_id_invalid_zero_and_reserved_fail_closed(self) -> None:
        for inbound_connection in (b"\x80\x00", b"\x7f\xff", b"\xff\xff"):
            with self.assertRaises(TransactionRejected):
                create_call_transaction(
                    outer_ctpp_handle=OuterCtppHandle(7),
                    serialized_ctp_packet=self.make_invite_packet(connection=inbound_connection),
                )
        self.assertEqual(derive_native_local_connection_id(b"\x12\x34"), b"\x92\x34")

    def test_open_and_stop_mediareq26_body_fields_match_r29c_lineage(self) -> None:
        media_channel_id = 0x3456
        open_body = build_mediareq26_open(media_channel_id)
        stop_body = build_mediareq26_stop(media_channel_id)
        self.assertEqual(len(open_body), 26)
        self.assertEqual(open_body[0:2], b"\x00\x11")
        self.assertEqual(open_body[2], 0x14)
        self.assertEqual(open_body[3], 0x32)
        self.assertEqual(struct.unpack_from("<I", open_body, 4)[0], 0)
        self.assertEqual(struct.unpack_from("<H", open_body, 8)[0], media_channel_id)
        self.assertEqual(struct.unpack_from("<H", open_body, 10)[0], 0xFFFF)
        self.assertEqual(struct.unpack_from("<H", open_body, 16)[0], 800)
        self.assertEqual(struct.unpack_from("<H", open_body, 18)[0], 480)
        self.assertEqual(struct.unpack_from("<H", open_body, 20)[0], 320)
        self.assertEqual(struct.unpack_from("<H", open_body, 22)[0], 240)
        self.assertEqual(open_body[24], 16)
        self.assertEqual(open_body[25], 0)

        self.assertEqual(len(stop_body), 26)
        self.assertEqual(stop_body[0:2], b"\x00\x11")
        self.assertEqual(stop_body[2], 0x94)
        self.assertEqual(stop_body[3], 0x00)
        self.assertEqual(struct.unpack_from("<I", stop_body, 4)[0], 0)
        self.assertEqual(struct.unpack_from("<H", stop_body, 8)[0], media_channel_id)
        self.assertEqual(stop_body[10:26], b"\x00" * 16)

    def test_historical_negative_preserves_r29c_bare_body_on_outer_ctpp_handle(self) -> None:
        self.assertIn("write_le16(out + 0, 0x1100u)", self.r29c_source)
        self.assertIn("out[2] = 0x14u", self.r29c_source)
        self.assertIn("out[2] = 0x94u", self.r29c_source)
        self.assertIn("write_le16(out + 8, r29c_saved_media_channel_id)", self.r29c_source)
        self.assertIn(
            "p12_queue_vip_frame(v4_ctpp_channel_id, body, 26u, kind)",
            self.r29c_source,
        )

    def test_structural_lineage_anchors_existing_full_packet_shape(self) -> None:
        self.assertIn("static p76_u32 p76_build_client_001a(", self.p76_source)
        self.assertIn("p76_write_be16(out + 8, 0x0011u);", self.p76_source)
        self.assertIn("out[10] = 0x14; out[11] = 0x32;", self.p76_source)
        self.assertIn("p76_write_le16(out + 16, target_id);", self.p76_source)
        self.assertIn("p76_write_le16(out + 24, 800u);", self.p76_source)
        self.assertIn("return 60u;", self.p76_source)

    def test_offline_purity_regression_for_new_model_and_test_modules(self) -> None:
        combined = self.model_source + "\n" + self.test_source
        forbidden_patterns = (
            r"(^|\n)\s*(import|from)\s+" + "so" + r"cket\b",
            r"\b" + "so" + r"cket\.",
            r"(^|\n)\s*(import|from)\s+" + "sub" + r"process\b",
            r"(^|\n)\s*(import|from)\s+" + "ur" + r"llib\b",
            r"(^|\n)\s*(import|from)\s+" + "req" + r"uests\b",
            r"(^|\n)\s*(import|from)\s+" + "ht" + r"tp\b",
            r"(^|\n)\s*(import|from)\s+" + "ss" + r"l\b",
            r"(?<![A-Za-z0-9_])" + "cu" + r"rl\s",
            r"(?<![A-Za-z0-9_])" + "nc" + r"\s",
            r"(?<![A-Za-z0-9_])" + "nc" + r"at\s",
            r"Pseudo" + r"TCP",
            r"ICE_" + r"GATHER",
            r"cloud_" + r"bootstrap",
            r"ha\." + r"services",
        )
        for pattern in forbidden_patterns:
            self.assertIsNone(re.search(pattern, combined, flags=re.MULTILINE))

    def test_type_separation_rejects_outer_handle_as_any_connection_id(self) -> None:
        transaction = self.make_transaction()
        from entrance_p116_r30b_call_transaction_model import toggle_direction_bit

        with self.assertRaises(TypeError):
            toggle_direction_bit(transaction.outer_ctpp_handle)  # type: ignore[arg-type]
        transaction.peer_connection_id = transaction.outer_ctpp_handle  # type: ignore[assignment]
        with self.assertRaises(TypeError):
            transaction.peer_connection_id = toggle_direction_bit(transaction.peer_connection_id)

    def test_ack_does_not_advance_sequence_and_body_packets_advance_once_each(self) -> None:
        from entrance_p116_r30b_call_transaction_model import InterceptedWriter

        transaction = self.make_transaction(seed=0xFE)
        transaction.next_tx_sequence = 0xFE
        writer = InterceptedWriter()
        transaction.intercept_transport_ack(writer)
        self.assertEqual(transaction.next_tx_sequence, 0xFE)
        transaction.intercept_capability_stage()
        transaction.intercept_alerting_stage()
        transaction.reach_call_signaling_order_barrier()
        transaction.allocate_media_channel(lambda: 0x3456)
        open_write = transaction.intercept_media_open(writer)
        self.assertEqual(open_write.sequence, 0xFE)
        self.assertEqual(transaction.next_tx_sequence, 0xFF)
        stop_write = transaction.intercept_media_stop(writer)
        self.assertEqual(stop_write.sequence, 0xFF)
        self.assertEqual(transaction.next_tx_sequence, 0x00)
        self.assertEqual(transaction.next_tx_acknowledgement, 0x56)

    def test_required_unknown_and_allocator_markers_remain_explicit(self) -> None:
        self.assertEqual(MEDIA_CHANNEL_ALLOCATOR_STATUS, "OFFLINE_COMPONENT_ONLY")
        self.assertEqual(OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE, "PROVEN")

    def test_forbidden_counters_are_read_only_zero_properties(self) -> None:
        writer = InterceptedWriter()
        for name in (
            "network_writes",
            "door_actions",
            "gate_actions",
            "self_activation_actions",
            "refresh_or_repeat_actions",
        ):
            self.assertEqual(getattr(writer, name), 0)
            with self.assertRaises((AttributeError, TypeError)):
                setattr(writer, name, 1)
            self.assertEqual(getattr(writer, name), 0)
        self.assertFalse(hasattr(writer, "__dict__"))


if __name__ == "__main__":
    unittest.main()
