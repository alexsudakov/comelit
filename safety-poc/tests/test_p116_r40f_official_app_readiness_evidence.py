"""P116 R40F focused tests -- readiness evidence overlay gate model and closure document.

Offline only. No network, no sockets, no device contact, no listener interaction. Exercises the
`entrance_p116_r40f_official_app_readiness_model` overlay against synthetic observations and against the
real R39 safe-scalar fixture (imported as data, never as a live capture), checks that the R40 model this
overlay narrows is untouched and still importable, and checks the R40F closure document for its required
invariants and evidence ledger.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = TESTS_DIR.parent / "research" / "media" / "v1"
R39_FIXTURE_PATH = TESTS_DIR / "fixtures" / "p116_r39_phone_capture_scalars.json"
R40_MODEL_PATH = RESEARCH_DIR / "entrance_p116_r40_official_app_readiness_model.py"
MODEL_PATH = RESEARCH_DIR / "entrance_p116_r40f_official_app_readiness_model.py"
CLOSURE_PATH = RESEARCH_DIR / "P116_R40F_OFFICIAL_APP_READINESS_EVIDENCE.md"
R40_CLOSURE_PATH = RESEARCH_DIR / "P116_R40_OFFICIAL_APP_READINESS_CLOSURE.md"
R41_PLAN_PATH = RESEARCH_DIR / "P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md"

IPV4_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise AssertionError(f"{name} not importable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODEL = _load_module(MODEL_PATH, "p116_r40f_readiness_model")


class R40ModelUntouchedTests(unittest.TestCase):
    """R40F must not rewrite the R40 model or closure -- only overlay/extend them."""

    def test_r40_model_file_still_exists_and_imports(self) -> None:
        self.assertTrue(R40_MODEL_PATH.exists())
        r40_model = _load_module(R40_MODEL_PATH, "p116_r40_readiness_model_from_r40f_test")
        observation = r40_model.ReadinessObservation(
            operator_app_state=r40_model.OperatorAppState.OPERATOR_CONFIRMED_USABLE,
            listener_state=r40_model.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = r40_model.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertTrue(verdict.physical_ring_allowed)

    def test_r40_closure_document_still_exists(self) -> None:
        self.assertTrue(R40_CLOSURE_PATH.exists())

    def test_r41_plan_still_exists_and_unrewritten_marker_present(self) -> None:
        self.assertTrue(R41_PLAN_PATH.exists())
        text = R41_PLAN_PATH.read_text(encoding="utf-8")
        self.assertIn("CONTRACT_ONLY", text)


class ReadinessModelPositiveTests(unittest.TestCase):
    def test_connected_ui_paused_budget_available_allows_ring(self) -> None:
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.CONNECTED,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertTrue(verdict.physical_ring_allowed)

    def test_connected_ui_corroborated_by_machine_signal_allows_ring(self) -> None:
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.CONNECTED,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
            registration_ready_seen=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertTrue(verdict.physical_ring_allowed)
        self.assertIn("confirmed_by_machine_signal", verdict.reason)

    def test_connected_ui_no_budget_is_ready_but_no_ring(self) -> None:
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.CONNECTED,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=False,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertFalse(verdict.physical_ring_allowed)


class ReadinessModelFailClosedTests(unittest.TestCase):
    def test_unknown_ui_state_is_unproven(self) -> None:
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.UNKNOWN,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_not_connected_ui_is_not_ready(self) -> None:
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.NOT_CONNECTED,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_connecting_ui_is_not_ready(self) -> None:
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.CONNECTING,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_connected_ui_contradicted_by_machine_signal_blocks_ring(self) -> None:
        """A stale/misread toolbar icon must never override a machine-observed non-registered
        state -- the machine signal, when explicitly sampled false, wins."""
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.CONNECTED,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
            registration_ready_seen=False,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_connected_ui_but_listener_still_ready_blocks_ring(self) -> None:
        """The R39 failure mode: a ring while the listener still owns the upstream session reaches
        the listener, not the official app -- must never be allowed, even with a connected UI."""
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.CONNECTED,
            listener_state=MODEL.ListenerState.READY,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_connected_ui_but_listener_down_blocks_ring(self) -> None:
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.CONNECTED,
            listener_state=MODEL.ListenerState.DOWN,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_connected_ui_but_listener_state_unknown_is_unproven(self) -> None:
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.CONNECTED,
            listener_state=MODEL.ListenerState.UNKNOWN,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)


class NetworkContextNotLoadBearingTests(unittest.TestCase):
    """Direct encoding of the R39 lesson, preserved unchanged from R40: TLS + STUN + UDP keepalive
    were all present while the official app was not ready, so none of them may ever promote
    readiness, even under the R40F overlay's new UI/machine signal fields."""

    def test_full_network_activity_without_connected_ui_stays_not_ready(self) -> None:
        saturated_context = MODEL.NetworkContextScalars(
            tls_session_present=True,
            stun_present=True,
            udp_keepalive_present=True,
            peer_count=8,
        )
        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.CONNECTING,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
            network_context=saturated_context,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_network_context_is_never_load_bearing_for_any_ui_state(self) -> None:
        saturated_context = MODEL.NetworkContextScalars(
            tls_session_present=True, stun_present=True, udp_keepalive_present=True, peer_count=8
        )
        for state in MODEL.OfficialAppUiConnectionState:
            for listener_state in MODEL.ListenerState:
                for budget in (True, False):
                    for registration_ready_seen in (None, True, False):
                        observation = MODEL.ReadinessObservation(
                            ui_state=state,
                            listener_state=listener_state,
                            ring_budget_available=budget,
                            registration_ready_seen=registration_ready_seen,
                            network_context=saturated_context,
                        )
                        MODEL.assert_network_context_not_load_bearing(observation)

    def test_r39_real_transport_categories_do_not_unlock_readiness(self) -> None:
        """Feeds the actual committed R39 fixture's transport_categories through the adapter and
        confirms the resulting context still cannot move the verdict without a connected UI read."""
        fixture = json.loads(R39_FIXTURE_PATH.read_text(encoding="utf-8"))
        transport_categories = fixture["capture_expectations"]["transport_categories"]
        peer_count = fixture["capture_expectations"]["peer_count"]
        context = MODEL.network_context_from_transport_categories(transport_categories, peer_count)
        self.assertTrue(context.tls_session_present)
        self.assertTrue(context.stun_present)
        self.assertTrue(context.udp_keepalive_present)
        self.assertEqual(context.peer_count, 8)

        observation = MODEL.ReadinessObservation(
            ui_state=MODEL.OfficialAppUiConnectionState.UNKNOWN,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
            network_context=context,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)


class ModelSourceHygieneTests(unittest.TestCase):
    def test_model_has_no_network_surface(self) -> None:
        source = MODEL_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import socket",
            "import requests",
            "urllib",
            "http.client",
            "subprocess",
            "asyncio",
        ):
            self.assertNotIn(forbidden, source)

    def test_evaluate_readiness_does_not_reference_network_context_attribute(self) -> None:
        source = MODEL_PATH.read_text(encoding="utf-8")
        start = source.index("def evaluate_readiness")
        end = source.index("\ndef ", start + 1)
        body = source[start:end]
        self.assertNotIn(".network_context", body)


@unittest.skipUnless(CLOSURE_PATH.exists(), "R40F closure document not yet written")
class ClosureDocumentInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = CLOSURE_PATH.read_text(encoding="utf-8")

    def test_closure_contains_canonical_block(self) -> None:
        self.assertIn("=== COMELIT P116 R40F READINESS EVIDENCE ===", self.doc)
        self.assertIn("=== END COMELIT P116 R40F READINESS EVIDENCE ===", self.doc)

    def test_closure_carries_executor_provenance(self) -> None:
        self.assertIn("EXECUTOR=claude-code-cli", self.doc)
        self.assertIn("EXECUTOR_SUBSTITUTION_AUTHORIZED_BY_USER=true", self.doc)
        self.assertIn("BASE_R40_SHA=123c1fd046f5d74956e89e795b439be379594f97", self.doc)

    def test_closure_keeps_zero_live_invariants(self) -> None:
        for token in (
            "PHYSICAL_RING_COUNT=0",
            "LISTENER_PAUSE_COUNT=0",
            "LISTENER_RESUME_COUNT=0",
            "NETWORK_TX_TO_COMELIT=0",
            "DOOR_ACTIONS=0",
            "GATE_ACTIONS=0",
            "DEPLOYS=0",
            "HA_RESTARTS=0",
            "HA_RELOADS=0",
            "RING_BUDGET_CONSUMED=false",
            "NEXT_LIVE_AUTHORIZED=false",
        ):
            self.assertIn(token, self.doc)

    def test_closure_states_scope_invariants(self) -> None:
        for token in (
            "PRODUCTION_FILES_CHANGED=0",
            "NORMATIVE_DOCS_CHANGED=0",
            "NATIVE_PRODUCTION_BINARY_CHANGED=false",
        ):
            self.assertIn(token, self.doc)

    def test_closure_cites_the_real_evidence_paths(self) -> None:
        for needle in (
            "ComelitStatus.java",
            "ToolbarUtilsKt",
            "DoorEntryContentFragment.java",
            "ReadFromJsonSocket.java",
            "ComelitEngineConnector.java",
            "subunit_fsm_status_change",
            "VipUnitImpl::new_call_ctp_conn",
        ):
            self.assertIn(needle, self.doc)

    def test_closure_never_promotes_transport_only_signal_to_proof(self) -> None:
        lowered = self.doc.lower()
        self.assertIn("r39", lowered)
        self.assertIn("keepalive", lowered)
        self.assertIn("not sufficient", lowered)

    def test_closure_does_not_reference_excluded_oauth_evidence(self) -> None:
        self.assertNotIn("oauth-evidence/", self.doc)

    def test_closure_is_address_free(self) -> None:
        matches = [m for m in IPV4_RE.findall(self.doc) if m not in {"0.0.0.0"}]
        self.assertEqual(matches, [])

    def test_closure_has_no_credential_or_token_like_strings(self) -> None:
        lowered = self.doc.lower()
        for forbidden in ("bearer ", "authorization: ", "-----begin"):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
