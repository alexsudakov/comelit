#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_p116_r28_listener_attached_media_transform as r28


class P116R28ListenerAttachedMediaTests(unittest.TestCase):
    def model(self) -> r28.ListenerAttachedInboundMediaModel:
        return r28.ListenerAttachedInboundMediaModel()

    def test_call_init_arm(self) -> None:
        model = self.model()
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertEqual(model.media_state, r28.MediaState.ARMED)
        self.assertTrue(model.diagnostics.armed)

    def test_no_media_before_call_init(self) -> None:
        model = self.model()
        self.assertFalse(model.start_attached_media())
        self.assertEqual(model.diagnostics.rtpc_channels_opened, 0)

    def test_unknown_source_does_not_start_media(self) -> None:
        model = self.model()
        self.assertFalse(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.UNKNOWN))
        self.assertFalse(model.start_attached_media())
        self.assertTrue(model.diagnostics.unknown_source_rejected)

    def test_entrance_gate_state_not_mixed(self) -> None:
        model = self.model()
        model.call = r28.CallTransactionState(active=True, source=r28.Source.GATE, generation=1)
        model.media_state = r28.MediaState.ARMED
        self.assertFalse(model.start_attached_media())
        self.assertTrue(model.diagnostics.entrance_gate_mixed)

    def test_registration_state_not_replaced_by_media_state(self) -> None:
        model = self.model()
        generation = model.registration.generation
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertTrue(model.start_attached_media())
        self.assertEqual(model.registration.generation, generation)
        self.assertFalse(model.registration.replaced_by_media)

    def test_no_new_ice_bootstrap(self) -> None:
        model = self.model()
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertTrue(model.start_attached_media())
        self.assertFalse(model.diagnostics.new_ice_bootstrap)

    def test_no_new_cloud_negotiation(self) -> None:
        model = self.model()
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertTrue(model.start_attached_media())
        self.assertFalse(model.diagnostics.new_cloud_negotiation)

    def test_no_new_pseudotcp_session(self) -> None:
        model = self.model()
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertTrue(model.start_attached_media())
        self.assertFalse(model.diagnostics.new_pseudotcp_session)

    def test_no_new_registration(self) -> None:
        model = self.model()
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertTrue(model.start_attached_media())
        self.assertFalse(model.diagnostics.new_registration)

    def test_call_transaction_state_separated_from_registration(self) -> None:
        model = self.model()
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertNotEqual(model.call.generation, model.registration.generation + 1)
        self.assertIs(model.call.source, r28.Source.ENTRANCE)
        self.assertTrue(model.registration.ready)

    def test_rtpc_allocation_uses_proven_runtime_semantics(self) -> None:
        model = self.model()
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertTrue(model.start_attached_media())
        self.assertEqual(model.diagnostics.rtpc_channels_opened, 2)
        self.assertTrue(model.emit_h264_rtp_to_loopback_boundary(3))
        self.assertEqual(model.diagnostics.loopback_boundary, "H264RecoveryRtpShim")
        self.assertEqual(model.diagnostics.rtp_packets_emitted, 3)

    def test_media_teardown_does_not_tear_down_persistent_transport(self) -> None:
        model = self.model()
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertTrue(model.start_attached_media())
        self.assertTrue(model.teardown_media())
        self.assertTrue(model.registration.ready)
        self.assertTrue(model.diagnostics.media_teardown_preserved_transport)
        self.assertTrue(model.diagnostics.media_teardown_preserved_registration)

    def test_second_call_init_during_media_fails_closed_or_serializes(self) -> None:
        model = self.model()
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertTrue(model.start_attached_media())
        self.assertFalse(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertTrue(model.diagnostics.second_call_init_blocked)

    def test_teardown_idempotent(self) -> None:
        model = self.model()
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertTrue(model.start_attached_media())
        self.assertTrue(model.teardown_media())
        self.assertTrue(model.teardown_media())
        self.assertEqual(model.teardown_count, 2)
        self.assertFalse(model.call.active)

    def test_malformed_signaling_no_media(self) -> None:
        model = self.model()
        self.assertFalse(model.observe_signal(r28.SignalKind.MALFORMED, r28.Source.ENTRANCE))
        self.assertFalse(model.start_attached_media())
        self.assertTrue(model.diagnostics.malformed_rejected)

    def test_no_door_action(self) -> None:
        model = self.model()
        self.assertFalse(model.request_door())
        self.assertFalse(model.diagnostics.door_action_sent)

    def test_no_gate_action(self) -> None:
        model = self.model()
        self.assertFalse(model.request_gate())
        self.assertFalse(model.diagnostics.gate_action_sent)

    def test_no_refresh_loop(self) -> None:
        model = self.model()
        self.assertFalse(model.start_refresh_loop())
        self.assertFalse(model.diagnostics.refresh_loop_started)

    def test_no_third_party_runtime_dependency(self) -> None:
        tree = ast.parse((MEDIA / "entrance_p116_r28_listener_attached_media_transform.py").read_text(encoding="utf-8"))
        imports = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
                imports.add((node.module or "").split(".")[0])
        self.assertLessEqual(imports, {"argparse", "dataclasses", "enum", "pathlib"})

    def test_transport_reuse_unknown_seam_defaults_closed(self) -> None:
        model = r28.ListenerAttachedInboundMediaModel(
            evidence=r28.EvidenceFlags(transport_reuse_proven=False)
        )
        self.assertTrue(model.observe_signal(r28.SignalKind.CALL_INIT, r28.Source.ENTRANCE))
        self.assertFalse(model.start_attached_media())
        self.assertTrue(model.diagnostics.failed_closed)

    def test_no_loopback_socket_bind_in_transform(self) -> None:
        tree = ast.parse((MEDIA / "entrance_p116_r28_listener_attached_media_transform.py").read_text(encoding="utf-8"))
        banned_socket_methods = {"bind", "connect", "connect_ex", "send", "sendall", "sendmsg", "sendto"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertNotIn("socket", {alias.name.split(".")[0] for alias in node.names})
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "socket")
            elif isinstance(node, ast.Name):
                self.assertNotEqual(node.id, "socket")
            elif isinstance(node, ast.Attribute):
                self.assertFalse(isinstance(node.value, ast.Name) and node.value.id == "socket")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, banned_socket_methods)


if __name__ == "__main__":
    unittest.main()
