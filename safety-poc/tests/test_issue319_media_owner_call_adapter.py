#!/usr/bin/env python3
"""Offline acceptance matrix for Issue #319 R10."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
MODULE = MEDIA / "issue319_media_owner_call_adapter.py"
sys.path.insert(0, str(MEDIA))
SPEC = importlib.util.spec_from_file_location("issue319_adapter", MODULE)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def harness(outcomes=(), ownership=None):
    writer = m.FakeWriter(outcomes)
    own = ownership or m.MediaOwnership(9, "rtpc-existing")
    adapter = m.MediaOwnerCallAdapter(writer, own)
    identity = m.CallIdentity("protocol-call-319", 9, 0x1234)
    return adapter, writer, m.FakePeer(identity)


def drain(adapter, writer, limit=20):
    for _ in range(limit):
        if writer.slot is None:
            adapter.arbiter.dispatch()
        if writer.slot is None:
            break
        adapter.writable()


class Issue319MediaOwnerCallAdapterTests(unittest.TestCase):
    def test_active_p78_initial_plus_four_retransmits_is_one_event(self):
        adapter, writer, peer = harness()
        for frame in peer.initial_and_retransmits():
            adapter.receive_call_init(frame)
        self.assertEqual(adapter.logical_call_events, 1)
        drain(adapter, writer)
        self.assertEqual([x.subject for x in writer.sent_frames], ["INVITE_ACK", "CAPABILITIES", "ALERTING"])
        self.assertEqual(len(writer.intents), 3)
        self.assertEqual(adapter.state, m.State.WAIT_PEER_CAPABILITIES)

    def test_genuine_second_call_same_generation_is_ambiguity_not_suppression(self):
        adapter, writer, peer = harness([m.FlushResult.EWOULDBLOCK])
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        second = m.CallIdentity("genuine-second", 9, 0x2222)
        result = adapter.receive_call_init(m.PeerFrame("CALL_INIT", second, sequence=1))
        self.assertEqual(result.state, m.State.OBSERVE_ONLY)
        self.assertIn("ambiguous", result.reason)
        self.assertEqual(adapter.logical_call_events, 1)

    def test_early_peer_capabilities_waits_for_local_triplet(self):
        adapter, writer, peer = harness()
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        adapter.receive_peer_capabilities(peer.capabilities(early=True))
        drain(adapter, writer)
        self.assertEqual([x.subject for x in writer.sent_frames], ["INVITE_ACK", "CAPABILITIES", "ALERTING", "PEER_ACK"])
        self.assertEqual(adapter.state, m.State.MEDIA_BIND_DECISION)

    def test_foreign_stale_malformed_and_absent_response(self):
        adapter, writer, peer = harness()
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        before = len(writer.intents)
        adapter.receive_peer_capabilities(peer.foreign_capabilities())
        adapter.receive_peer_capabilities(m.PeerFrame("CAPABILITIES", None, malformed=True))
        self.assertEqual(len(writer.intents), before)
        drain(adapter, writer)
        self.assertEqual(adapter.state, m.State.WAIT_PEER_CAPABILITIES)
        stale = adapter.receive_peer_capabilities(peer.stale_capabilities())
        self.assertEqual(stale.state, m.State.FAIL_CLOSED)
        self.assertEqual(adapter.retry_count, 0)

        absent, awriter, apeer = harness()
        absent.receive_call_init(apeer.initial_and_retransmits(0)[0])
        drain(absent, awriter)
        self.assertEqual(absent.tick_timeout().state, m.State.FAIL_CLOSED)
        no_identity, nwriter, _ = harness()
        self.assertEqual(
            no_identity.receive_call_init(m.PeerFrame("CALL_INIT", None)).state,
            m.State.FAIL_CLOSED,
        )
        self.assertEqual(nwriter.intents, [])

    def test_partial_and_ewouldblock_only_progress_on_full_flush(self):
        outcomes = [m.FlushResult.PARTIAL, m.FlushResult.EWOULDBLOCK, m.FlushResult.COMPLETE]
        adapter, writer, peer = harness(outcomes)
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        adapter.writable()
        self.assertEqual(adapter.state, m.State.ACK_FLUSH)
        adapter.writable()
        self.assertEqual(adapter.state, m.State.ACK_FLUSH)
        adapter.writable()
        self.assertEqual(adapter.state, m.State.CAPABILITIES_FLUSH)
        self.assertEqual(writer.transmitted_frame_count, 0)

    def test_r45_r53_contract_modules_own_wire_bytes_and_profile(self):
        adapter, writer, peer = harness()
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        assert writer.slot and adapter.serializer
        ack = writer.slot.intent.frame
        self.assertEqual(ack[0], m.r45.CTP_FLAG_EMPTY_ACK)
        self.assertEqual(ack[1], m.r45.CTP_VERSION)
        self.assertEqual(int.from_bytes(ack[2:4], "big"), peer.identity.connection)
        self.assertEqual(ack[5], 8)
        self.assertEqual(int.from_bytes(ack[6:8], "big"), 0)
        self.assertEqual(len(ack), 32)
        self.assertEqual(
            adapter.profile,
            m.R53ProfileAdapter(*m.r53.helper_runtime_fields()),
        )
        self.assertIs(m.R45SerializerAdapter.capabilities.__globals__["r45"], m.r45)

        delegated = m.R45SerializerAdapter(peer.identity.connection)
        direct_ack = m.r45.build_empty_ack(
            connection=peer.identity.connection,
            local_sequence=0,
            peer_sequence=7,
            source_logical=delegated.source_logical,
            dest_logical=delegated.dest_logical,
        )
        self.assertEqual(delegated.invite_ack(7), direct_ack)
        direct_capabilities = m.r45.build_packet(
            flags=m.r45.CTP_FLAG_DATA,
            connection=peer.identity.connection,
            sequence=0,
            acknowledgement=8,
            body=m.r45.serialize_capabilities(*m.r53.helper_runtime_fields()[:2]),
            source_logical=delegated.source_logical,
            dest_logical=delegated.dest_logical,
        )
        self.assertEqual(
            delegated.capabilities(*m.r53.helper_runtime_fields()[:2]),
            direct_capabilities,
        )

    def test_timeout_and_late_generation_completion_fail_closed(self):
        adapter, writer, peer = harness([m.FlushResult.TIMEOUT])
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        self.assertEqual(adapter.writable().state, m.State.FAIL_CLOSED)
        self.assertEqual(adapter.retry_count, 0)
        adapter2, writer2, peer2 = harness()
        adapter2.receive_call_init(peer2.initial_and_retransmits(0)[0])
        assert writer2.slot
        writer2.slot.intent = m.WriteIntent("INVITE_ACK", b"x", 8, m.Priority.ADOPTION)
        self.assertEqual(adapter2.writable().state, m.State.FAIL_CLOSED)
        self.assertIn("late_completion", adapter2.reason)

    def test_failure_keeps_partial_slot_until_real_late_completion(self):
        adapter, writer, peer = harness([m.FlushResult.PARTIAL, m.FlushResult.COMPLETE])
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        adapter.writable()
        assert writer.slot
        offset = writer.slot.offset
        result = adapter.receive_peer_capabilities(peer.stale_capabilities())
        self.assertEqual(result.state, m.State.FAIL_CLOSED)
        self.assertIsNotNone(writer.slot)
        self.assertEqual(writer.slot.offset, offset)
        adapter.writable()
        self.assertIsNone(writer.slot)
        self.assertEqual([x.subject for x in writer.sent_frames], ["INVITE_ACK"])
        self.assertEqual(adapter.state, m.State.FAIL_CLOSED)

    def test_p12_priority_single_slot_and_refresh_index_preserved(self):
        adapter, writer, peer = harness([m.FlushResult.EWOULDBLOCK])
        refresh = m.WriteIntent("R27_REFRESH", b"r", 9, m.Priority.R27_REFRESH)
        selfact = m.WriteIntent("SELF_ACTIVATION", b"s", 9, m.Priority.SELF_ACTIVATION)
        adapter.arbiter.pending.extend([(selfact, adapter.arbiter.completed), (refresh, adapter.arbiter.completed)])
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        adapter.arbiter.dispatch()
        self.assertEqual(writer.slot.intent.subject, "INVITE_ACK")
        self.assertEqual(adapter.arbiter.refresh_index, 0)
        adapter.writable()  # EWOULDBLOCK: slot ownership is retained.
        self.assertEqual(writer.slot.intent.subject, "INVITE_ACK")
        drain(adapter, writer)
        self.assertEqual(adapter.arbiter.refresh_index, 1)
        subjects = [x.subject for x in writer.sent_frames]
        self.assertEqual(len(subjects), len(set(subjects)))

    def test_preoccupied_p12_slot_waits_without_double_write(self):
        adapter, writer, peer = harness()
        existing = m.WriteIntent("R27_REFRESH", b"refresh", 9, m.Priority.R27_REFRESH)
        self.assertTrue(writer.enqueue(existing, adapter.arbiter.completed))
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        self.assertEqual(writer.slot.intent.subject, "R27_REFRESH")
        self.assertEqual(adapter.state, m.State.ACK_FLUSH)
        adapter.writable()
        adapter.arbiter.dispatch()
        self.assertEqual(writer.slot.intent.subject, "INVITE_ACK")
        self.assertEqual(adapter.arbiter.refresh_index, 1)

    def test_failure_preserves_foreign_slot_queue_and_refresh_index(self):
        adapter, writer, peer = harness()
        refresh = m.WriteIntent("R27_REFRESH", b"refresh", 9, m.Priority.R27_REFRESH)
        selfact = m.WriteIntent("SELF_ACTIVATION", b"self", 9, m.Priority.SELF_ACTIVATION)
        self.assertTrue(writer.enqueue(refresh, adapter.arbiter.completed))
        adapter.arbiter.pending.append((selfact, adapter.arbiter.completed))
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        self.assertEqual(adapter.receive_peer_capabilities(peer.stale_capabilities()).state, m.State.FAIL_CLOSED)
        assert writer.slot
        self.assertEqual(writer.slot.intent.subject, "R27_REFRESH")
        self.assertEqual([x[0].subject for x in adapter.arbiter.pending], ["SELF_ACTIVATION"])
        adapter.writable()
        self.assertEqual(adapter.arbiter.refresh_index, 1)
        assert writer.slot
        self.assertEqual(writer.slot.intent.subject, "SELF_ACTIVATION")
        adapter.writable()
        self.assertEqual([x.subject for x in writer.sent_frames], ["R27_REFRESH", "SELF_ACTIVATION"])

    def test_existing_rebind_and_switch_require_proof(self):
        adapter, writer, peer = harness()
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        adapter.receive_peer_capabilities(peer.capabilities(early=True))
        drain(adapter, writer)
        result = adapter.decide_media_bind("rtpc-existing")
        self.assertEqual(result.decision, m.MediaBindDecision.EXISTING_CHANNEL_REBIND)

        switch, swriter, speer = harness()
        switch.receive_call_init(speer.initial_and_retransmits(0)[0])
        switch.receive_peer_capabilities(speer.capabilities(early=True))
        drain(switch, swriter)
        denied = switch.decide_media_bind("rtpc-new", old_channel_closed_confirmed=False)
        self.assertEqual(denied.decision, m.MediaBindDecision.UNSUPPORTED_FAIL_CLOSED)
        self.assertEqual(swriter.sent_frames[-1].subject, "PEER_ACK")

    def test_confirmed_switch_still_has_one_upstream(self):
        adapter, writer, peer = harness()
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        adapter.receive_peer_capabilities(peer.capabilities(early=True))
        drain(adapter, writer)
        result = adapter.decide_media_bind("rtpc-new", old_channel_closed_confirmed=True)
        self.assertEqual(result.decision, m.MediaBindDecision.SINGLE_UPSTREAM_CHANNEL_SWITCH)
        self.assertEqual(adapter.ownership.upstream_count, 1)

    def test_media_bind_rejects_unproven_ambiguous_and_terminal_ownership(self):
        ownerships = (
            m.MediaOwnership(9, "rtpc-existing", owner_proven=False),
            m.MediaOwnership(9, "rtpc-existing", upstream_count=2),
            m.MediaOwnership(9, "rtpc-existing", receiver_terminal=True),
            m.MediaOwnership(9, "rtpc-existing", teardown_uncertain=True),
        )
        for ownership in ownerships:
            with self.subTest(ownership=ownership):
                adapter, writer, peer = harness(ownership=ownership)
                adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
                adapter.receive_peer_capabilities(peer.capabilities(early=True))
                drain(adapter, writer)
                result = adapter.decide_media_bind(
                    "rtpc-new", old_channel_closed_confirmed=True
                )
                self.assertEqual(result.state, m.State.FAIL_CLOSED)
                self.assertEqual(
                    result.decision, m.MediaBindDecision.UNSUPPORTED_FAIL_CLOSED
                )

    def test_receiver_terminal_and_teardown_uncertainty_no_retry(self):
        for action in ("receiver_terminated", "teardown_became_uncertain"):
            adapter, writer, _peer = harness()
            result = getattr(adapter, action)()
            self.assertEqual(result.state, m.State.FAIL_CLOSED)
            self.assertEqual(adapter.retry_count, 0)
            self.assertEqual(writer.sent_frames, [])
            result = adapter.receive_call_init(
                m.PeerFrame("CALL_INIT", m.CallIdentity("later", 9, 1), sequence=3)
            )
            self.assertEqual(result.state, m.State.FAIL_CLOSED)
            self.assertEqual(writer.intents, [])

    def test_terminal_event_mid_adoption_preserves_current_slot(self):
        for action in ("receiver_terminated", "teardown_became_uncertain"):
            with self.subTest(action=action):
                adapter, writer, peer = harness([m.FlushResult.PARTIAL])
                adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
                adapter.writable()
                assert writer.slot
                slot = writer.slot
                result = getattr(adapter, action)()
                self.assertEqual(result.state, m.State.FAIL_CLOSED)
                self.assertIs(writer.slot, slot)
                self.assertGreater(writer.slot.offset, 0)
                adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
                self.assertEqual(len(writer.intents), 1)

    def test_observe_only_is_terminal_and_cannot_restart(self):
        adapter, writer, _peer = harness()
        unknown = m.CallIdentity("unknown-scope", 9, 0)
        first = adapter.receive_call_init(m.PeerFrame("CALL_INIT", unknown, sequence=1))
        self.assertEqual(first.state, m.State.OBSERVE_ONLY)
        valid = m.CallIdentity("later-valid", 9, 44)
        second = adapter.receive_call_init(m.PeerFrame("CALL_INIT", valid, sequence=2))
        self.assertEqual(second.state, m.State.OBSERVE_ONLY)
        self.assertEqual(writer.intents, [])

    def test_offline_boundary_counters_and_owner_of_truth(self):
        adapter, writer, peer = harness()
        adapter.receive_call_init(peer.initial_and_retransmits(0)[0])
        drain(adapter, writer)
        self.assertEqual(writer.transmitted_frame_count, 0)
        self.assertEqual(writer.network_primitive_count, 0)
        self.assertEqual(writer.real_producer_count, 0)
        self.assertEqual(writer.audio_tx_count, 0)
        self.assertEqual(writer.door_action_count + writer.gate_action_count, 0)
        self.assertEqual(writer.event_ring_count, 0)
        with self.assertRaises(AttributeError):
            writer.transmitted_frame_count = 1
        fields = set(m.CallIdentity.__dataclass_fields__)
        self.assertEqual(fields, {"call_id", "owner_generation", "connection"})
        for surrogate in ("episode_id", "frame_sha", "time_window"):
            self.assertNotIn(surrogate, MODULE.read_text(encoding="utf-8"))

    def test_no_production_import_path_or_network_primitives(self):
        text = MODULE.read_text(encoding="utf-8")
        tree = ast.parse(text)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(any(name == "socket" or name.startswith("socket.") for name in imports))
        self.assertTrue(all(not name.startswith("custom_components") for name in imports))
        self.assertTrue({"send", "sendall", "sendto", "connect"}.isdisjoint(calls))
        self.assertNotIn("custom_components.comelit", text)
        self.assertNotIn("entrance_p116_r54_call_adoption_listener_transform", text)
        for token in ("import socket", "socket.socket", "sendto(", "connect(", "EVENT_RING"):
            self.assertNotIn(token, text)

    def test_packaged_native_helpers_match_base_evidence(self):
        expected = {
            "comelit-media": "2a10b69e6c7e0565fa088b509904df1779478f0227fbbb8f6d4ba12034d8f045",
            "comelit-v4": "0f1798bff9527b50fe6f72c2be7c10000cd1d1d08472da8ccb35aa08da3edbab",
        }
        native = ROOT.parent / "custom_components" / "comelit" / "native"
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((native / name).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
