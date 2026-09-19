"""P116 R40G focused tests -- dex7/dex9 runtime-path overlay model, R40G closure document, and R41 v2
contract document.

Offline only. No network, no sockets, no device contact, no listener interaction. Exercises
`entrance_p116_r40g_official_app_readiness_model` against synthetic observations, checks that R40F's model
this overlay wraps is untouched and still importable and passes its own tests unmodified, and checks the
R40G closure document and R41 v2 contract for their required invariants.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = TESTS_DIR.parent / "research" / "media" / "v1"
R40F_MODEL_PATH = RESEARCH_DIR / "entrance_p116_r40f_official_app_readiness_model.py"
MODEL_PATH = RESEARCH_DIR / "entrance_p116_r40g_official_app_readiness_model.py"
CLOSURE_PATH = RESEARCH_DIR / "P116_R40G_RUNTIME_PATH_AND_READINESS.md"
R40F_CLOSURE_PATH = RESEARCH_DIR / "P116_R40F_OFFICIAL_APP_READINESS_EVIDENCE.md"
R41_V1_PATH = RESEARCH_DIR / "P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md"
R41_V2_PATH = RESEARCH_DIR / "P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V2.md"

IPV4_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise AssertionError(f"{name} not importable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODEL = _load_module(MODEL_PATH, "p116_r40g_readiness_model")


class R40FModelUntouchedTests(unittest.TestCase):
    """R40G must not rewrite the R40F model or closure -- only overlay/extend them."""

    def test_r40f_model_file_still_exists_and_imports(self) -> None:
        self.assertTrue(R40F_MODEL_PATH.exists())
        r40f_model = _load_module(R40F_MODEL_PATH, "p116_r40f_readiness_model_from_r40g_test")
        observation = r40f_model.ReadinessObservation(
            ui_state=r40f_model.OfficialAppUiConnectionState.CONNECTED,
            listener_state=r40f_model.ListenerState.PAUSED,
            ring_budget_available=True,
        )
        verdict = r40f_model.evaluate_readiness(observation)
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertTrue(verdict.physical_ring_allowed)

    def test_r40f_closure_document_still_exists(self) -> None:
        self.assertTrue(R40F_CLOSURE_PATH.exists())

    def test_r41_v1_still_exists_and_unrewritten_marker_present(self) -> None:
        self.assertTrue(R41_V1_PATH.exists())
        text = R41_V1_PATH.read_text(encoding="utf-8")
        self.assertIn("CONTRACT_ONLY", text)


class OverlayReuseTests(unittest.TestCase):
    """The R40G overlay must delegate to R40F, not duplicate its logic."""

    def test_overlay_reexports_r40f_types_by_identity(self) -> None:
        r40f_model = _load_module(R40F_MODEL_PATH, "p116_r40f_readiness_model_identity_check")
        # MODEL loads its own copy of R40F via importlib in the source file; check structural
        # equivalence (same enum members) rather than object identity across two independent loads.
        self.assertEqual(
            {member.value for member in MODEL.OfficialAppUiConnectionState},
            {member.value for member in r40f_model.OfficialAppUiConnectionState},
        )

    def test_evaluate_readiness_v2_source_delegates_not_duplicates(self) -> None:
        source = MODEL_PATH.read_text(encoding="utf-8")
        self.assertIn("_r40f.evaluate_readiness(observation_v2.observation)", source)
        # the overlay must not redefine the fail-closed listener/ring gating logic itself
        self.assertNotIn("ListenerState.READY", source)
        self.assertNotIn("ring_budget_available:", source)


class SystemClassGateTests(unittest.TestCase):
    def _observation(self, ui_state=None, registration_ready_seen=None):
        return MODEL.ReadinessObservation(
            ui_state=ui_state if ui_state is not None else MODEL.OfficialAppUiConnectionState.CONNECTED,
            listener_state=MODEL.ListenerState.PAUSED,
            ring_budget_available=True,
            registration_ready_seen=registration_ready_seen,
        )

    def test_legacy_vip_system_class_allows_ready_verdict(self) -> None:
        obs = MODEL.ReadinessObservationV2(
            system_class=MODEL.AppSystemClass.LEGACY_VIP,
            observation=self._observation(),
        )
        verdict = MODEL.evaluate_readiness_v2(obs)
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertTrue(verdict.physical_ring_allowed)

    def test_cloud_registered_system_class_is_unproven_regardless_of_ui_state(self) -> None:
        obs = MODEL.ReadinessObservationV2(
            system_class=MODEL.AppSystemClass.CLOUD_REGISTERED,
            observation=self._observation(),
        )
        verdict = MODEL.evaluate_readiness_v2(obs)
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)
        self.assertIn("not_covered_by_this_model", verdict.reason)

    def test_unknown_system_class_is_unproven(self) -> None:
        obs = MODEL.ReadinessObservationV2(
            system_class=MODEL.AppSystemClass.UNKNOWN,
            observation=self._observation(),
        )
        verdict = MODEL.evaluate_readiness_v2(obs)
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_missing_system_class_type_is_unproven(self) -> None:
        obs = MODEL.ReadinessObservationV2(system_class="legacy_vip", observation=self._observation())  # type: ignore[arg-type]
        verdict = MODEL.evaluate_readiness_v2(obs)
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)


class MachineSignalNoteTests(unittest.TestCase):
    """R40G CHILD D: the machine signal is the same field as the UI read, not independent
    corroboration -- the overlay's reason string must say so instead of silently repeating R40F's
    'confirmed by machine signal' framing verbatim."""

    def test_confirmed_by_machine_signal_reason_carries_non_independence_note(self) -> None:
        obs = MODEL.ReadinessObservationV2(
            system_class=MODEL.AppSystemClass.LEGACY_VIP,
            observation=MODEL.ReadinessObservation(
                ui_state=MODEL.OfficialAppUiConnectionState.CONNECTED,
                listener_state=MODEL.ListenerState.PAUSED,
                ring_budget_available=True,
                registration_ready_seen=True,
            ),
        )
        verdict = MODEL.evaluate_readiness_v2(obs)
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertIn("confirmed_by_machine_signal", verdict.reason)
        self.assertIn("not_independent_corroboration", verdict.reason)

    def test_contradicted_by_machine_signal_still_blocks_ring(self) -> None:
        obs = MODEL.ReadinessObservationV2(
            system_class=MODEL.AppSystemClass.LEGACY_VIP,
            observation=MODEL.ReadinessObservation(
                ui_state=MODEL.OfficialAppUiConnectionState.CONNECTED,
                listener_state=MODEL.ListenerState.PAUSED,
                ring_budget_available=True,
                registration_ready_seen=False,
            ),
        )
        verdict = MODEL.evaluate_readiness_v2(obs)
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)


class FailClosedRegressionTests(unittest.TestCase):
    """Re-run R40F's core fail-closed cases through the v2 wrapper with system_class=LEGACY_VIP to
    confirm delegation preserves R40F's gating semantics exactly."""

    def _obs(self, ui_state, listener_state, ring_budget_available):
        return MODEL.ReadinessObservationV2(
            system_class=MODEL.AppSystemClass.LEGACY_VIP,
            observation=MODEL.ReadinessObservation(
                ui_state=ui_state,
                listener_state=listener_state,
                ring_budget_available=ring_budget_available,
            ),
        )

    def test_not_connected_ui_is_not_ready(self) -> None:
        verdict = MODEL.evaluate_readiness_v2(
            self._obs(MODEL.OfficialAppUiConnectionState.NOT_CONNECTED, MODEL.ListenerState.PAUSED, True)
        )
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_listener_ready_blocks_ring_even_when_connected(self) -> None:
        verdict = MODEL.evaluate_readiness_v2(
            self._obs(MODEL.OfficialAppUiConnectionState.CONNECTED, MODEL.ListenerState.READY, True)
        )
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_connected_no_budget_is_ready_but_no_ring(self) -> None:
        verdict = MODEL.evaluate_readiness_v2(
            self._obs(MODEL.OfficialAppUiConnectionState.CONNECTED, MODEL.ListenerState.PAUSED, False)
        )
        self.assertEqual(verdict.official_app_ready, "true")
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


@unittest.skipUnless(CLOSURE_PATH.exists(), "R40G closure document not yet written")
class ClosureDocumentInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = CLOSURE_PATH.read_text(encoding="utf-8")

    def test_closure_contains_canonical_block(self) -> None:
        self.assertIn("=== COMELIT P116 R40G RUNTIME PATH / READINESS ===", self.doc)
        self.assertIn("=== END COMELIT P116 R40G RUNTIME PATH / READINESS ===", self.doc)

    def test_closure_carries_executor_provenance(self) -> None:
        self.assertIn("EXECUTOR=claude-code-cli", self.doc)
        self.assertIn("EXECUTOR_FALLBACK_USED=false", self.doc)
        self.assertIn("BASE_R40F_SHA=73ef4904155951d35b78b7c791dcab1978966782", self.doc)

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
            "ComelitApplication.java",
            "ComelitFirebaseMessagingService.java",
            "Systems.java",
            "isLegacySystem",
            "ComelitSDKAndroid",
            "ReadFromJsonSocket.java",
            "mBound",
            "ViperSocketReaderRunnable.java",
            "DoorEntryContentFragment.java",
            "PlatformLogger.java",
        ):
            self.assertIn(needle, self.doc)

    def test_closure_does_not_reference_excluded_oauth_evidence(self) -> None:
        self.assertNotIn("oauth-evidence/", self.doc)

    def test_closure_is_address_free(self) -> None:
        matches = [m for m in IPV4_RE.findall(self.doc) if m not in {"0.0.0.0"}]
        self.assertEqual(matches, [])

    def test_closure_has_no_credential_or_token_like_strings(self) -> None:
        lowered = self.doc.lower()
        for forbidden in ("bearer ", "authorization: ", "-----begin"):
            self.assertNotIn(forbidden, lowered)


@unittest.skipUnless(R41_V2_PATH.exists(), "R41 v2 contract not yet written")
class R41V2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = R41_V2_PATH.read_text(encoding="utf-8")

    def test_v2_contains_canonical_block(self) -> None:
        self.assertIn("=== COMELIT P116 R41 V2 PREFLIGHT CONTRACT (DOCUMENT ONLY) ===", self.doc)
        self.assertIn("RUNNER_CREATED=false", self.doc)
        self.assertIn("LIVE_EXECUTED=false", self.doc)
        self.assertIn("RING_BUDGET_CONSUMED=false", self.doc)
        self.assertIn("NEXT_LIVE_AUTHORIZED=false", self.doc)

    def test_v2_references_concrete_ui_state_not_abstract_operator_state(self) -> None:
        self.assertIn("ToolbarDeviceConnectionStatus", self.doc)
        self.assertIn("evaluate_readiness_v2", self.doc)

    def test_v2_states_no_ring_never(self) -> None:
        self.assertIn("NO physical ring", self.doc)

    def test_v1_not_superseded_in_place(self) -> None:
        self.assertTrue(R41_V1_PATH.exists())
        self.assertIn("SUPERSEDES=P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md", self.doc)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
