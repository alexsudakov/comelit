from __future__ import annotations

import re
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
MODEL_SOURCE = MEDIA / "entrance_p116_r34_attached_media_helper_model.py"
DOC_SOURCE = MEDIA / "P116_R34_ATTACHED_INBOUND_MEDIA_OFFLINE_IMPLEMENTATION.md"
TEST_SOURCE = Path(__file__).resolve()

sys.path.insert(0, str(MEDIA))
from entrance_p116_r30_call_ctp_envelope_model import (  # noqa: E402
    build_call_bound_media_packet,
    parse_ctp_envelope,
)
from entrance_p116_r30b_call_transaction_model import (  # noqa: E402
    InterceptedWrite,
    InterceptedWriter,
    OuterCtppHandle,
    build_mediareq26_open as r30b_build_mediareq26_open,
)
from entrance_p116_r34_attached_media_helper_model import (  # noqa: E402
    MEDIAREQ26_BODY_LENGTH,
    MEDIAREQ26_FORM_ADDRESS,
    MEDIAREQ26_FORM_TUNNEL,
    MEDIAREQ26_INNER_OPCODE,
    MEDIAREQ26_OPEN_ACTION,
    MEDIAREQ26_STOP_ACTION,
    MEDIAREQ26_UNKNOWN_FIELDS,
    MediaRequest26Sources,
    R34AttachedMediaRejected,
    R34AttachedMediaSession,
    create_session_at_call_barrier,
    default_open_sources,
    derive_gates,
    open_flags,
    parse_mediareq26,
    report,
    run_offline_attached_media_trace,
    second_open_forbidden_reasons,
    serialize_call_bound_media_open,
    serialize_call_bound_media_stop,
    serialize_mediareq26_open,
    serialize_mediareq26_stop,
    stop_flags,
)


class P116R34AttachedMediaOfflineImpl(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model_source = MODEL_SOURCE.read_text(encoding="utf-8")
        cls.doc_source = DOC_SOURCE.read_text(encoding="utf-8")
        cls.test_source = TEST_SOURCE.read_text(encoding="utf-8")

    def test_01_happy_path_call_init_to_open_stop_dispose_order(self) -> None:
        session = run_offline_attached_media_trace()
        self.assertEqual(
            session.events,
            [
                "CALL_TRANSACTION_CAPTURED",
                "MEDIA_CHANNEL_UNALLOCATED",
                "MEDIA_RX_CHANNEL_ALLOCATED",
                "CHANNEL_ALLOCATED_OPEN_REQUESTED",
                "CALL_BOUND_MEDIAREQ26_OPEN",
                "MEDIA_OPEN_EMITTED",
                "MEDIA_ACTIVE_RTP_ELIGIBLE",
                "CHANNEL_OPEN_RESPONSE_PASS",
                "CALL_BOUND_MEDIAREQ26_STOP",
                "MEDIA_STOP_EMITTED",
                "MEDIA_RX_CHANNEL_DISPOSED",
                "MEDIA_CHANNEL_DISPOSED",
                "LISTENER_REGISTRATION_PSEUDOTCP_CALL_TRANSACTION_PRESERVED",
            ],
        )
        self.assertEqual(session.open_count, 1)
        self.assertEqual(session.stop_count, 1)
        self.assertTrue(session.rtp_eligible is False)
        gates = derive_gates(session)
        self.assertTrue(gates["CALL_CTP_CAPTURE_IMPLEMENTED"])
        self.assertTrue(gates["STOP_ORDER_GATE"])

    def test_02_exact_mediareq26_and_call_bound_packet_serialization(self) -> None:
        sources = default_open_sources(
            form=MEDIAREQ26_FORM_ADDRESS,
            video_request=True,
            profile_selector=True,
        )
        body = serialize_mediareq26_open(sources)
        parsed = parse_mediareq26(body)
        self.assertEqual(len(body), 26)
        self.assertEqual(parsed["unknown_fields"], 0)
        self.assertEqual(body[0:2], struct.pack(">H", MEDIAREQ26_INNER_OPCODE))
        self.assertEqual(body[2], MEDIAREQ26_OPEN_ACTION)
        self.assertEqual(body[3], 0x3C)
        self.assertEqual(body[4:8], b"\x01\x02\x03\x04")
        self.assertEqual(struct.unpack_from("<H", body, 8)[0], 0x3456)
        self.assertEqual(struct.unpack_from("<H", body, 10)[0], 0x04D2)
        self.assertEqual(struct.unpack_from("<I", body, 12)[0], 0x00001234)
        self.assertEqual(struct.unpack_from("<H", body, 16)[0], 0x0320)
        self.assertEqual(struct.unpack_from("<H", body, 18)[0], 0x01E0)
        self.assertEqual(struct.unpack_from("<H", body, 20)[0], 0x0140)
        self.assertEqual(struct.unpack_from("<H", body, 22)[0], 0x00F0)
        self.assertEqual(body[24], 0x10)
        self.assertEqual(body[25], 0)
        session = create_session_at_call_barrier()
        packet = serialize_call_bound_media_open(session.transaction, sources)  # type: ignore[arg-type]
        self.assertEqual(len(packet), 60)
        self.assertEqual(parse_ctp_envelope(packet).inner_body, body)
        self.assertEqual(MEDIAREQ26_UNKNOWN_FIELDS, 0)

    def test_03_open_flags_are_source_expressions_for_tunnel_and_address(self) -> None:
        self.assertEqual(open_flags(form=MEDIAREQ26_FORM_TUNNEL, video_request=False), 0x32)
        self.assertEqual(open_flags(form=MEDIAREQ26_FORM_TUNNEL, video_request=True), 0x3A)
        self.assertEqual(open_flags(form=MEDIAREQ26_FORM_ADDRESS, video_request=False), 0x30)
        self.assertEqual(open_flags(form=MEDIAREQ26_FORM_ADDRESS, video_request=True), 0x38)
        self.assertEqual(
            open_flags(
                form=MEDIAREQ26_FORM_ADDRESS,
                video_request=True,
                profile_selector=True,
            ),
            0x3C,
        )
        self.assertNotEqual(
            serialize_mediareq26_open(default_open_sources(video_request=False))[3],
            serialize_mediareq26_open(default_open_sources(video_request=True))[3],
        )
        self.assertNotEqual(
            serialize_mediareq26_open(default_open_sources(form=MEDIAREQ26_FORM_ADDRESS, video_request=False))[3],
            serialize_mediareq26_open(default_open_sources(form=MEDIAREQ26_FORM_ADDRESS, video_request=True))[3],
        )

    def test_04_stop_serialization_zeroes_open_only_fields(self) -> None:
        for form, expected_flags in ((MEDIAREQ26_FORM_TUNNEL, 0x02), (MEDIAREQ26_FORM_ADDRESS, 0x00)):
            body = serialize_mediareq26_stop(form=form, media_channel_id=0x3456)
            self.assertEqual(len(body), 26)
            self.assertEqual(body[2], MEDIAREQ26_STOP_ACTION)
            self.assertEqual(body[3], expected_flags)
            self.assertEqual(struct.unpack_from("<H", body, 8)[0], 0x3456)
            self.assertEqual(body[10:26], b"\x00" * 16)
            session = create_session_at_call_barrier()
            packet = serialize_call_bound_media_stop(
                session.transaction,  # type: ignore[arg-type]
                form=form,
                media_channel_id=0x3456,
            )
            self.assertEqual(len(packet), 60)
            self.assertEqual(parse_ctp_envelope(packet).inner_body, body)
            self.assertEqual(stop_flags(form=form), expected_flags)

    def test_05_open_stop_bind_to_direction_transformed_call_ctp_id(self) -> None:
        session = run_offline_attached_media_trace()
        open_write = _single_write(session.writer, "MEDIA_OPEN")
        stop_write = _single_write(session.writer, "MEDIA_STOP")
        open_packet = parse_ctp_envelope(open_write.serialized_ctp_packet)
        stop_packet = parse_ctp_envelope(stop_write.serialized_ctp_packet)
        self.assertEqual(open_packet.connection, session.call_ctp_id)
        self.assertEqual(stop_packet.connection, session.call_ctp_id)
        self.assertNotEqual(open_packet.connection, struct.pack(">H", session.outer_ctpp_handle.value))

    def test_06_registration_handle_open_rejected_without_write(self) -> None:
        session = create_session_at_call_barrier()
        session.allocate_media_rx_channel(0x3456)
        before = len(session.writer.writes)
        with self.assertRaises(R34AttachedMediaRejected):
            session.send_open(default_open_sources(), use_registration_handle=True)
        self.assertEqual(len(session.writer.writes), before)

    def test_07_second_open_rejection_iterates_all_seven_conditions(self) -> None:
        self.assertEqual(len(second_open_forbidden_reasons()), 7)
        for state in second_open_forbidden_reasons():
            with self.subTest(state=state.code):
                session = _session_for_second_open_state(state.code)
                before = session.open_count
                with self.assertRaises(R34AttachedMediaRejected):
                    session.send_open(default_open_sources(), use_registration_handle=_uses_registration(state.code))
                self.assertEqual(session.open_count, before)

    def test_08_stop_before_open_rejected(self) -> None:
        session = create_session_at_call_barrier()
        channel = session.allocate_media_rx_channel(0x3456)
        with self.assertRaises(R34AttachedMediaRejected):
            session.send_stop(form=MEDIAREQ26_FORM_TUNNEL, channel_id=channel.channel_id, token=channel.token)

    def test_09_wrong_and_stale_channel_uses_rejected(self) -> None:
        session = create_session_at_call_barrier()
        channel = session.allocate_media_rx_channel(0x3456)
        session.send_open(default_open_sources())
        with self.assertRaises(R34AttachedMediaRejected):
            session.observe_channel_open_response(channel_id=0x3457)
        with self.assertRaises(R34AttachedMediaRejected):
            session.send_stop(form=MEDIAREQ26_FORM_TUNNEL, channel_id=0x3457)
        session.send_stop(form=MEDIAREQ26_FORM_TUNNEL, channel_id=channel.channel_id, token=channel.token)
        with self.assertRaises(R34AttachedMediaRejected):
            session.dispose_media_rx_channel(channel_id=0x3457)
        session.dispose_media_rx_channel(channel_id=channel.channel_id, token=channel.token)
        with self.assertRaises(R34AttachedMediaRejected):
            session.enable_rtp(channel_id=channel.channel_id, token=channel.token)

    def test_10_dispose_before_stop_rejected(self) -> None:
        session = create_session_at_call_barrier()
        channel = session.allocate_media_rx_channel(0x3456)
        session.send_open(default_open_sources())
        with self.assertRaises(R34AttachedMediaRejected):
            session.dispose_media_rx_channel(channel_id=channel.channel_id, token=channel.token)

    def test_11_structural_zero_properties_are_read_only(self) -> None:
        session = run_offline_attached_media_trace()
        for name in (
            "network_tx",
            "new_ice",
            "new_cloud",
            "new_pseudotcp",
            "new_registration",
            "door_actions",
            "gate_actions",
        ):
            self.assertEqual(getattr(session, name), 0)
            with self.assertRaises(AttributeError):
                setattr(session, name, 1)

    def test_12_persistent_listener_registration_pseudotcp_call_preserved(self) -> None:
        session = run_offline_attached_media_trace()
        self.assertTrue(session.listener_alive)
        self.assertTrue(session.registration_alive)
        self.assertTrue(session.pseudotcp_alive)
        self.assertTrue(session.call_transaction_alive)
        self.assertTrue(derive_gates(session)["LISTENER_PRESERVATION_MODEL"])

    def test_13_door_and_gate_actions_zero(self) -> None:
        session = run_offline_attached_media_trace()
        self.assertEqual(session.door_actions, 0)
        self.assertEqual(session.gate_actions, 0)
        gates = derive_gates(session)
        self.assertEqual(gates["DOOR_ACTIONS"], 0)
        self.assertEqual(gates["GATE_ACTIONS"], 0)

    def test_14_no_real_tx_and_source_scan_stays_offline(self) -> None:
        session = run_offline_attached_media_trace()
        self.assertEqual(session.network_tx, 0)
        self.assertEqual(session.writer.network_writes, 0)
        self.assertEqual(len(session.writer.writes), 3)
        combined = self.model_source + "\n" + self.test_source + "\n" + self.doc_source
        forbidden_patterns = (
            r"(^|\n)\s*(import|from)\s+" + "so" + r"cket\b",
            r"(^|\n)\s*(import|from)\s+" + "ss" + r"l\b",
            r"(^|\n)\s*(import|from)\s+" + "ht" + r"tp\b",
            r"(^|\n)\s*(import|from)\s+" + "ur" + r"llib\b",
            r"(^|\n)\s*(import|from)\s+" + "req" + r"uests\b",
            r"(^|\n)\s*(import|from)\s+" + "ai" + r"ohttp\b",
            r"(^|\n)\s*(import|from)\s+" + "sub" + r"process\b",
            r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
            r"\b" + "cu" + r"rl\s",
            r"\b" + "nc" + r"\s",
        )
        for pattern in forbidden_patterns:
            self.assertIsNone(re.search(pattern, combined, flags=re.MULTILINE))

    def test_15_reuses_r30_models_and_cross_checks_proven_open_offsets(self) -> None:
        ours = serialize_mediareq26_open(default_open_sources(video_request=False))
        old = r30b_build_mediareq26_open(0x3456)
        self.assertEqual(ours[0:3], old[0:3])
        self.assertEqual(ours[3], 0x32)
        self.assertEqual(ours[3], old[3])
        self.assertEqual(ours[4:10], old[4:10])
        self.assertIn("from entrance_p116_r30_call_ctp_envelope_model import", self.model_source)
        self.assertIn("build_call_bound_media_packet", self.model_source)
        self.assertIn("from entrance_p116_r30b_call_transaction_model import", self.model_source)
        self.assertIn("create_trace_at_call_barrier", self.model_source)
        self.assertNotIn("def build_ctp_envelope(", self.model_source)
        self.assertNotIn("class CallTransaction", self.model_source)

    def test_16_derivation_flips_and_report_prints_failure_markers(self) -> None:
        open_corrupt = run_offline_attached_media_trace()
        open_corrupt.writer.writes.append(_single_write(open_corrupt.writer, "MEDIA_OPEN"))
        self.assertFalse(derive_gates(open_corrupt)["OPEN_COUNT_GATE"])
        self.assertIn("OPEN_COUNT_GATE=FAIL", report(open_corrupt))

        order_corrupt = run_offline_attached_media_trace()
        stop_index = order_corrupt.events.index("CALL_BOUND_MEDIAREQ26_STOP")
        dispose_index = order_corrupt.events.index("MEDIA_RX_CHANNEL_DISPOSED")
        order_corrupt.events[stop_index], order_corrupt.events[dispose_index] = (
            order_corrupt.events[dispose_index],
            order_corrupt.events[stop_index],
        )
        self.assertFalse(derive_gates(order_corrupt)["STOP_ORDER_GATE"])
        self.assertIn("STOP_ORDER_GATE=FAIL", report(order_corrupt))

        registered_corrupt = run_offline_attached_media_trace()
        open_write = _single_write(registered_corrupt.writer, "MEDIA_OPEN")
        body = parse_ctp_envelope(open_write.serialized_ctp_packet).inner_body
        outer_connection = struct.pack(">H", registered_corrupt.outer_ctpp_handle.value)
        packet = build_call_bound_media_packet(
            local_connection=outer_connection,
            sequence=open_write.sequence,
            acknowledgement=open_write.acknowledgement,
            mediareq26=body,
            source_raw=registered_corrupt.transaction.source_logical_address,  # type: ignore[union-attr]
            destination_raw=registered_corrupt.transaction.destination_logical_address,  # type: ignore[union-attr]
        )
        registered_corrupt.writer.writes[1] = InterceptedWrite(
            semantic_kind="MEDIA_OPEN",
            outer_ctpp_handle=registered_corrupt.outer_ctpp_handle,
            serialized_ctp_packet=packet,
            call_connection_id=outer_connection,
            sequence=open_write.sequence,
            acknowledgement=open_write.acknowledgement,
            inner_opcode=MEDIAREQ26_INNER_OPCODE,
            inner_length=MEDIAREQ26_BODY_LENGTH,
        )
        self.assertFalse(derive_gates(registered_corrupt)["REGISTERED_CTPP_MISUSE_GATE"])
        self.assertIn("REGISTERED_CTPP_MISUSE_GATE=FAIL", report(registered_corrupt))

    def test_17_document_result_block_and_no_placeholders(self) -> None:
        self.assertIn(
            "=== COMELIT P116 R34 ATTACHED MEDIA OFFLINE IMPLEMENTATION (REPO DOC) ===",
            self.doc_source,
        )
        self.assertIn(
            "=== END COMELIT P116 R34 ATTACHED MEDIA OFFLINE IMPLEMENTATION (REPO DOC) ===",
            self.doc_source,
        )
        self.assertNotRegex(self.doc_source, r"\b(TODO|TBD|PENDING|PLACEHOLDER)\b")


def _single_write(writer: InterceptedWriter, semantic_kind: str) -> InterceptedWrite:
    matches = [write for write in writer.writes if write.semantic_kind == semantic_kind]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {semantic_kind} write")
    return matches[0]


def _session_for_second_open_state(code: str) -> R34AttachedMediaSession:
    if code == "NO_CALL_TRANSACTION_CAPTURE_OR_SIGNALING_BARRIER":
        return R34AttachedMediaSession(
            writer=InterceptedWriter(),
            transaction=None,
            call_ctp_id=None,
            outer_ctpp_handle=OuterCtppHandle(7),
            call_ctp_valid=False,
        )
    session = create_session_at_call_barrier()
    if code == "NO_LOCAL_MEDIA_RX_CHANNEL_ALLOCATED":
        return session
    channel = session.allocate_media_rx_channel(0x3456)
    if code == "OPEN_ALREADY_PENDING":
        session.send_open(default_open_sources())
        return session
    if code == "OPEN_ALREADY_EMITTED_ACTIVE_OR_CONFIRMED":
        session.send_open(default_open_sources())
        session.observe_channel_open_response(channel_id=channel.channel_id, token=channel.token, ok=True)
        return session
    if code == "STOP_ALREADY_SENT":
        session.send_open(default_open_sources())
        session.send_stop(form=MEDIAREQ26_FORM_TUNNEL, channel_id=channel.channel_id, token=channel.token)
        return session
    if code == "MEDIA_CHANNEL_ALREADY_DISPOSED":
        session.send_open(default_open_sources())
        session.send_stop(form=MEDIAREQ26_FORM_TUNNEL, channel_id=channel.channel_id, token=channel.token)
        session.dispose_media_rx_channel(channel_id=channel.channel_id, token=channel.token)
        return session
    if code == "REGISTRATION_HANDLE_OR_FOREIGN_CALL_TRANSACTION":
        return session
    raise AssertionError(f"unhandled second-open code {code}")


def _uses_registration(code: str) -> bool:
    return code == "REGISTRATION_HANDLE_OR_FOREIGN_CALL_TRANSACTION"


if __name__ == "__main__":
    unittest.main()
