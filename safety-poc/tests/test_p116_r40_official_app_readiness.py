"""P116 R40 focused tests -- official-app readiness offline gate model and closure documents.

Offline only. No network, no sockets, no device contact, no listener interaction. Exercises the
fail-closed `OFFICIAL_APP_READY` / `PHYSICAL_RING_ALLOWED` gate model against synthetic observations
and against the real R39 safe-scalar fixture (imported as data, never as a live capture), and checks
the closure/plan documents for their required invariants.
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
MODEL_PATH = RESEARCH_DIR / "entrance_p116_r40_official_app_readiness_model.py"
CLOSURE_PATH = RESEARCH_DIR / "P116_R40_OFFICIAL_APP_READINESS_CLOSURE.md"
R41_PLAN_PATH = RESEARCH_DIR / "P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md"
R40_OFFLINE_PLAN_PATH = RESEARCH_DIR / "P116_R40_OFFICIAL_APP_READINESS_OFFLINE_PLAN.md"

IPV4_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def _load_model():
    spec = importlib.util.spec_from_file_location("p116_r40_readiness_model", MODEL_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise AssertionError("readiness model not importable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODEL = _load_model()


class ReadinessModelPositiveTests(unittest.TestCase):
    def test_confirmed_paused_budget_available_allows_ring(self) -> None:
        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.OPERATOR_CONFIRMED_USABLE,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertTrue(verdict.physical_ring_allowed)

    def test_confirmed_paused_no_budget_is_ready_but_no_ring(self) -> None:
        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.OPERATOR_CONFIRMED_USABLE,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=False,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertFalse(verdict.physical_ring_allowed)


class ReadinessModelFailClosedTests(unittest.TestCase):
    def test_unknown_operator_state_is_unproven(self) -> None:
        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.UNKNOWN,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_not_opened_is_not_ready(self) -> None:
        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.NOT_OPENED,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_loading_or_reconnecting_is_not_ready(self) -> None:
        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.LOADING_OR_RECONNECTING,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_error_or_offline_is_not_ready(self) -> None:
        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.ERROR_OR_OFFLINE,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_confirmed_but_listener_still_ready_blocks_ring(self) -> None:
        """The R39 failure mode: a ring while the listener still owns the upstream session reaches
        the listener, not the official app -- must never be allowed, even with a confirmed app."""
        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.OPERATOR_CONFIRMED_USABLE,
            listener_state=MODEL.ListenerState.READY,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_confirmed_but_listener_down_blocks_ring(self) -> None:
        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.OPERATOR_CONFIRMED_USABLE,
            listener_state=MODEL.ListenerState.DOWN,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_confirmed_but_listener_state_unknown_is_unproven(self) -> None:
        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.OPERATOR_CONFIRMED_USABLE,
            listener_state=MODEL.ListenerState.UNKNOWN,
            ring_budget_available=True,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)


class NetworkContextNotLoadBearingTests(unittest.TestCase):
    """Direct encoding of the R39 lesson: TLS + STUN + UDP keepalive were all present while the
    official app was not ready, so none of them may ever promote readiness."""

    def test_full_network_activity_without_operator_confirmation_stays_not_ready(self) -> None:
        saturated_context = MODEL.NetworkContextScalars(
            tls_session_present=True,
            stun_present=True,
            udp_keepalive_present=True,
            peer_count=8,
        )
        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.LOADING_OR_RECONNECTING,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
            network_context=saturated_context,
        )
        verdict = MODEL.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_network_context_is_never_load_bearing_for_any_operator_state(self) -> None:
        saturated_context = MODEL.NetworkContextScalars(
            tls_session_present=True, stun_present=True, udp_keepalive_present=True, peer_count=8
        )
        for state in MODEL.OperatorAppState:
            for listener_state in MODEL.ListenerState:
                for budget in (True, False):
                    observation = MODEL.ReadinessObservation(
                        operator_app_state=state,
                        listener_state=listener_state,
                        ring_budget_available=budget,
                        network_context=saturated_context,
                    )
                    MODEL.assert_network_context_not_load_bearing(observation)

    def test_r39_real_transport_categories_do_not_unlock_readiness(self) -> None:
        """Feeds the actual committed R39 fixture's transport_categories through the adapter and
        confirms the resulting context still cannot move the verdict without operator confirmation."""
        fixture = json.loads(R39_FIXTURE_PATH.read_text(encoding="utf-8"))
        transport_categories = fixture["capture_expectations"]["transport_categories"]
        peer_count = fixture["capture_expectations"]["peer_count"]
        context = MODEL.network_context_from_transport_categories(transport_categories, peer_count)
        self.assertTrue(context.tls_session_present)
        self.assertTrue(context.stun_present)
        self.assertTrue(context.udp_keepalive_present)
        self.assertEqual(context.peer_count, 8)

        observation = MODEL.ReadinessObservation(
            operator_app_state=MODEL.OperatorAppState.UNKNOWN,
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
        """Static guard, independent of the runtime check above: the function body itself must not
        contain the attribute access `.network_context`."""
        source = MODEL_PATH.read_text(encoding="utf-8")
        start = source.index("def evaluate_readiness")
        end = source.index("\ndef ", start + 1)
        body = source[start:end]
        self.assertNotIn(".network_context", body)


@unittest.skipUnless(CLOSURE_PATH.exists(), "closure document not yet written")
class ClosureDocumentInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = CLOSURE_PATH.read_text(encoding="utf-8")

    def test_closure_contains_canonical_block(self) -> None:
        self.assertIn("=== COMELIT P116 R40 OFFICIAL APP READINESS ===", self.doc)
        self.assertIn("=== END COMELIT P116 R40 OFFICIAL APP READINESS ===", self.doc)

    def test_closure_carries_executor_provenance(self) -> None:
        self.assertIn("EXECUTOR=claude-code-cli", self.doc)
        self.assertIn("EXECUTOR_SUBSTITUTION_AUTHORIZED_BY_USER=true", self.doc)

    def test_closure_keeps_zero_live_invariants(self) -> None:
        for field in (
            "PHYSICAL_RING_COUNT=0",
            "LISTENER_PAUSE_COUNT=0",
            "LISTENER_RESUME_COUNT=0",
            "NETWORK_TX=0",
            "DOOR_ACTIONS=0",
            "GATE_ACTIONS=0",
            "DEPLOYS=0",
            "HA_RESTARTS=0",
            "HA_RELOADS=0",
            "RING_BUDGET_CONSUMED=false",
            "NEXT_LIVE_AUTHORIZED=false",
        ):
            self.assertIn(field, self.doc)

    def test_closure_never_promotes_transport_only_signal_to_proof(self) -> None:
        lowered = self.doc.lower()
        self.assertIn("r39", lowered)
        self.assertIn("keepalive", lowered)
        self.assertIn("not sufficient", lowered)

    def test_closure_states_scope_invariants(self) -> None:
        for field in (
            "PRODUCTION_FILES_CHANGED=0",
            "NORMATIVE_DOCS_CHANGED=0",
            "NATIVE_PRODUCTION_BINARY_CHANGED=false",
        ):
            self.assertIn(field, self.doc)

    def test_closure_is_address_free(self) -> None:
        matches = [m for m in IPV4_RE.findall(self.doc) if m not in {"0.0.0.0"}]
        self.assertEqual(matches, [])


@unittest.skipUnless(R41_PLAN_PATH.exists(), "R41 plan not yet written")
class R41PlanInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = R41_PLAN_PATH.read_text(encoding="utf-8")

    def test_plan_keeps_no_ring_in_preflight(self) -> None:
        lowered = self.doc.lower()
        self.assertIn("no physical ring", lowered)

    def test_plan_keeps_ring_budget_unconsumed_on_both_outcomes(self) -> None:
        self.assertIn("BLOCKED_APP_NOT_READY", self.doc)
        self.assertIn("PASS_APP_READY_PREFLIGHT", self.doc)
        self.assertIn("RING_BUDGET_CONSUMED=false", self.doc)

    def test_plan_does_not_auto_authorize_next_round(self) -> None:
        lowered = self.doc.lower()
        self.assertIn("does not authorize", lowered)

    def test_plan_references_the_gate_model(self) -> None:
        self.assertIn("entrance_p116_r40_official_app_readiness_model.py", self.doc)

    def test_plan_is_address_free(self) -> None:
        matches = [m for m in IPV4_RE.findall(self.doc) if m not in {"0.0.0.0"}]
        self.assertEqual(matches, [])


class R40OfflinePlanUnchangedTests(unittest.TestCase):
    """R40 must not rewrite the existing offline plan; only reference it."""

    def test_offline_plan_file_still_exists_unreplaced(self) -> None:
        self.assertTrue(R40_OFFLINE_PLAN_PATH.exists())
        text = R40_OFFLINE_PLAN_PATH.read_text(encoding="utf-8")
        self.assertIn("plan only", text.lower())
        self.assertIn("NEXT_LIVE_AUTHORIZED=false", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
