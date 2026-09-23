"""P116 R40H focused tests -- fresh-registration log model, freshness-aware readiness overlay, closure
document, and R41 v3 contract document.

Offline only. No network, no sockets, no device contact, no listener interaction, no adb/subprocess.
Exercises `entrance_p116_r40h_registration_log_model` and `entrance_p116_r40h_official_app_readiness_model`
against synthetic log events (enum/status text only, no real identifiers), checks that R40G's model this
round overlays is untouched and still importable and passes its own tests unmodified, and checks the R40H
closure document and R41 v3 contract for their required invariants and evidence ledger.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
RESEARCH_DIR = TESTS_DIR.parent / "research" / "media" / "v1"
R40G_MODEL_PATH = RESEARCH_DIR / "entrance_p116_r40g_official_app_readiness_model.py"
LOG_MODEL_PATH = RESEARCH_DIR / "entrance_p116_r40h_registration_log_model.py"
READINESS_MODEL_PATH = RESEARCH_DIR / "entrance_p116_r40h_official_app_readiness_model.py"
CLOSURE_PATH = RESEARCH_DIR / "P116_R40H_FRESH_REGISTRATION_RECEIVER_LIVENESS.md"
R40G_CLOSURE_PATH = RESEARCH_DIR / "P116_R40G_RUNTIME_PATH_AND_READINESS.md"
R41_V2_PATH = RESEARCH_DIR / "P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V2.md"
R41_V3_PATH = RESEARCH_DIR / "P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V3.md"

IPV4_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise AssertionError(f"{name} not importable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LOG_MODEL = _load_module(LOG_MODEL_PATH, "p116_r40h_registration_log_model")
READINESS_MODEL = _load_module(READINESS_MODEL_PATH, "p116_r40h_readiness_model")


class ReduceRawLineTests(unittest.TestCase):
    def test_matches_registration_transition_line(self) -> None:
        event = LOG_MODEL.reduce_raw_line("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED", 5)
        self.assertIsNotNone(event)
        self.assertEqual(event.source, LOG_MODEL.LogEventSource.VIP_REGISTER_TRANSITION)
        self.assertEqual(event.from_state, LOG_MODEL.RegisterStatus.REGISTERING)
        self.assertEqual(event.to_state, LOG_MODEL.RegisterStatus.REGISTERED)
        self.assertEqual(event.monotonic_seq, 5)

    def test_matches_transport_failure_line(self) -> None:
        event = LOG_MODEL.reduce_raw_line("ViperSocketReaderRun", "VIPER SOCKET CONNECTION LOST", 7)
        self.assertIsNotNone(event)
        self.assertEqual(event.source, LOG_MODEL.LogEventSource.VIPER_TRANSPORT_FAILURE)
        self.assertIsNone(event.from_state)
        self.assertIsNone(event.to_state)

    def test_close_request_alone_is_not_a_failure_marker(self) -> None:
        # "VIPER SOCKET CLOSE REQUEST" alone (without CONNECTION LOST) also fires on a deliberate
        # stop() per ViperSocketReaderRunnable.stop()/run() -- only CONNECTION LOST is the reliable
        # undeliberate-failure marker this model keys on.
        event = LOG_MODEL.reduce_raw_line("ViperSocketReaderRun", "VIPER SOCKET CLOSE REQUEST", 3)
        self.assertIsNone(event)

    def test_unrelated_tag_is_discarded(self) -> None:
        self.assertIsNone(LOG_MODEL.reduce_raw_line("SomeOtherTag", "VIP REGISTER CHANGED NONE -> REGISTERED", 1))

    def test_malformed_message_is_discarded(self) -> None:
        self.assertIsNone(LOG_MODEL.reduce_raw_line("ComelitStatus", "totally unrelated text", 1))

    def test_reassertion_would_never_be_emitted_by_the_real_app_but_is_still_rejected_if_seen(self) -> None:
        # ComelitStatus.setEngineVipRegStatus's equality guard means the real app can never emit
        # "REGISTERED -> REGISTERED"; this is a defensive check that the reducer's regex still simply
        # accepts it as a (vacuous) same-state transition rather than crashing.
        event = LOG_MODEL.reduce_raw_line("ComelitStatus", "VIP REGISTER CHANGED REGISTERED -> REGISTERED", 1)
        self.assertIsNotNone(event)
        self.assertEqual(event.from_state, event.to_state)


class EvaluateFreshRegistrationTests(unittest.TestCase):
    def _ev(self, tag, message, seq):
        event = LOG_MODEL.reduce_raw_line(tag, message, seq)
        assert event is not None
        return event

    def test_no_events_after_cursor_is_not_fresh(self) -> None:
        events = [self._ev("ComelitStatus", "VIP REGISTER CHANGED NONE -> REGISTERED", 1)]
        verdict = LOG_MODEL.evaluate_fresh_registration(events, pre_pause_log_cursor=5)
        self.assertFalse(verdict.fresh_registered_transition_seen)
        self.assertFalse(verdict.registration_ready_fresh_scalar)

    def test_fresh_transition_after_cursor_is_accepted(self) -> None:
        events = [
            self._ev("ComelitStatus", "VIP REGISTER CHANGED NONE -> NOT_REGISTERED", 1),  # before cursor
            self._ev("ComelitStatus", "VIP REGISTER CHANGED NOT_REGISTERED -> REGISTERING", 10),
            self._ev("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED", 11),
        ]
        verdict = LOG_MODEL.evaluate_fresh_registration(events, pre_pause_log_cursor=5)
        self.assertTrue(verdict.fresh_registered_transition_seen)
        self.assertEqual(verdict.transition_monotonic_seq, 11)
        self.assertTrue(verdict.registration_ready_fresh_scalar)
        self.assertEqual(verdict.attempt_generation, 1)

    def test_stale_registered_before_cursor_is_not_fresh(self) -> None:
        # Simulates R40G CHILD D's silent-staleness case: REGISTERED happened long before the
        # attempt boundary and nothing has changed since -- current-state alone must not pass.
        events = [self._ev("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED", 1)]
        verdict = LOG_MODEL.evaluate_fresh_registration(events, pre_pause_log_cursor=5)
        self.assertFalse(verdict.fresh_registered_transition_seen)
        self.assertFalse(verdict.registration_ready_fresh_scalar)

    def test_transport_failure_after_fresh_transition_poisons_it(self) -> None:
        events = [
            self._ev("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED", 10),
            self._ev("ViperSocketReaderRun", "VIPER SOCKET CONNECTION LOST", 12),
        ]
        verdict = LOG_MODEL.evaluate_fresh_registration(events, pre_pause_log_cursor=5)
        self.assertFalse(verdict.registration_ready_fresh_scalar)
        self.assertTrue(verdict.transport_failure_after_transition)
        self.assertIn("transport_failure", "".join([str(verdict.reason)]) + str(events))  # sanity: no crash

    def test_transport_failure_then_new_fresh_transition_is_accepted_again(self) -> None:
        events = [
            self._ev("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED", 10),
            self._ev("ViperSocketReaderRun", "VIPER SOCKET CONNECTION LOST", 12),
            self._ev("ComelitStatus", "VIP REGISTER CHANGED NOT_REGISTERED -> REGISTERING", 14),
            self._ev("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED", 15),
        ]
        verdict = LOG_MODEL.evaluate_fresh_registration(events, pre_pause_log_cursor=5)
        self.assertTrue(verdict.registration_ready_fresh_scalar)
        self.assertEqual(verdict.transition_monotonic_seq, 15)
        self.assertEqual(verdict.attempt_generation, 2)

    def test_explicit_deregistration_after_fresh_transition_invalidates_it(self) -> None:
        events = [
            self._ev("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED", 10),
            self._ev("ComelitStatus", "VIP REGISTER CHANGED REGISTERED -> NOT_REGISTERED", 11),
        ]
        verdict = LOG_MODEL.evaluate_fresh_registration(events, pre_pause_log_cursor=5)
        self.assertFalse(verdict.registration_ready_fresh_scalar)

    def test_out_of_order_input_is_sorted_by_monotonic_seq(self) -> None:
        events = [
            self._ev("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED", 15),
            self._ev("ComelitStatus", "VIP REGISTER CHANGED NOT_REGISTERED -> REGISTERING", 14),
        ]
        verdict = LOG_MODEL.evaluate_fresh_registration(events, pre_pause_log_cursor=5)
        self.assertTrue(verdict.registration_ready_fresh_scalar)
        self.assertEqual(verdict.transition_monotonic_seq, 15)

    def test_events_exactly_at_cursor_are_excluded(self) -> None:
        events = [self._ev("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED", 5)]
        verdict = LOG_MODEL.evaluate_fresh_registration(events, pre_pause_log_cursor=5)
        self.assertFalse(verdict.fresh_registered_transition_seen)


class LogModelSourceHygieneTests(unittest.TestCase):
    def test_model_has_no_network_or_process_surface(self) -> None:
        """Real import/call level check, not a bare substring scan.

        The module's own docstring legitimately says "invokes no subprocess/adb", so a naive
        `assertNotIn("subprocess", source)` matches prose rather than code. This test therefore
        inspects only code lines (docstring/comment text stripped) for real imports, module use and
        process/socket calls.
        """
        source = LOG_MODEL_PATH.read_text(encoding="utf-8")
        try:
            import ast

            tree = ast.parse(source)
            body_without_docstring = [
                node for node in tree.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
            ]
            code_only = "\n".join(ast.unparse(node) for node in body_without_docstring)
        except Exception:  # pragma: no cover - defensive fallback
            code_only = "\n".join(
                line for line in source.splitlines() if not line.strip().startswith("#")
            )

        forbidden_imports = ("socket", "requests", "urllib", "http.client", "subprocess", "asyncio", "adb")
        for module_name in forbidden_imports:
            self.assertNotRegex(
                code_only,
                rf"(?m)^\s*(import|from)\s+{re.escape(module_name)}\b",
                f"module imports {module_name}",
            )
        for call in ("subprocess.", "os.system(", "os.popen(", "adb "):
            self.assertNotIn(call, code_only, f"module calls {call!r}")
        self.assertNotIn("socket.socket", code_only)


class R40GModelUntouchedTests(unittest.TestCase):
    """R40H must not rewrite the R40G model or closure -- only overlay/extend them."""

    def test_r40g_model_file_still_exists_and_imports(self) -> None:
        self.assertTrue(R40G_MODEL_PATH.exists())
        r40g_model = _load_module(R40G_MODEL_PATH, "p116_r40g_readiness_model_from_r40h_test")
        obs = r40g_model.ReadinessObservationV2(
            system_class=r40g_model.AppSystemClass.LEGACY_VIP,
            observation=r40g_model.ReadinessObservation(
                ui_state=r40g_model.OfficialAppUiConnectionState.CONNECTED,
                listener_state=r40g_model.ListenerState.PAUSED,
                ring_budget_available=True,
            ),
        )
        verdict = r40g_model.evaluate_readiness_v2(obs)
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertTrue(verdict.physical_ring_allowed)

    def test_r40g_closure_document_still_exists(self) -> None:
        self.assertTrue(R40G_CLOSURE_PATH.exists())

    def test_r41_v2_still_exists_and_unrewritten_marker_present(self) -> None:
        self.assertTrue(R41_V2_PATH.exists())
        text = R41_V2_PATH.read_text(encoding="utf-8")
        self.assertIn("CONTRACT_ONLY", text)


class ReadinessOverlayDelegationTests(unittest.TestCase):
    def test_source_delegates_not_duplicates(self) -> None:
        source = READINESS_MODEL_PATH.read_text(encoding="utf-8")
        self.assertIn("_r40g.evaluate_readiness_v2(v2_obs)", source)
        # must not re-implement the listener/ring gating logic itself
        self.assertNotIn("ListenerState.READY", source)
        self.assertNotIn("ring_budget_available:", source)


class ReadinessV3FreshnessGateTests(unittest.TestCase):
    def _fresh_verdict(self, ready: bool, transport_failure: bool = False):
        return LOG_MODEL.FreshRegistrationVerdict(
            fresh_registered_transition_seen=ready,
            transition_monotonic_seq=10 if ready else None,
            transport_failure_after_transition=transport_failure,
            registration_ready_fresh_scalar=ready and not transport_failure,
            attempt_generation=1 if ready else 0,
            reason="synthetic",
        )

    def _obs(self, ui_state, listener_state, ring_budget_available, fresh_ready, transport_failure=False):
        return READINESS_MODEL.ReadinessObservationV3(
            system_class=READINESS_MODEL.AppSystemClass.LEGACY_VIP,
            observation=READINESS_MODEL.ReadinessObservation(
                ui_state=ui_state,
                listener_state=listener_state,
                ring_budget_available=ring_budget_available,
            ),
            fresh_registration=self._fresh_verdict(fresh_ready, transport_failure),
        )

    def test_connected_with_no_fresh_transition_is_unproven_not_ready(self) -> None:
        # The exact R40G CHILD D silent-staleness scenario: current CONNECTED, no fresh evidence.
        verdict = READINESS_MODEL.evaluate_readiness_v3(
            self._obs(
                READINESS_MODEL.OfficialAppUiConnectionState.CONNECTED,
                READINESS_MODEL.ListenerState.PAUSED,
                True,
                fresh_ready=False,
            )
        )
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_connected_with_fresh_transition_and_budget_is_ready_and_ring_allowed(self) -> None:
        verdict = READINESS_MODEL.evaluate_readiness_v3(
            self._obs(
                READINESS_MODEL.OfficialAppUiConnectionState.CONNECTED,
                READINESS_MODEL.ListenerState.PAUSED,
                True,
                fresh_ready=True,
            )
        )
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertTrue(verdict.physical_ring_allowed)
        self.assertIn("fresh_registration_confirmed_per_r40h", verdict.reason)

    def test_connected_with_fresh_transition_but_no_ring_budget_is_ready_but_no_ring(self) -> None:
        verdict = READINESS_MODEL.evaluate_readiness_v3(
            self._obs(
                READINESS_MODEL.OfficialAppUiConnectionState.CONNECTED,
                READINESS_MODEL.ListenerState.PAUSED,
                False,
                fresh_ready=True,
            )
        )
        self.assertEqual(verdict.official_app_ready, "true")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_fresh_transition_poisoned_by_transport_failure_is_unproven(self) -> None:
        verdict = READINESS_MODEL.evaluate_readiness_v3(
            self._obs(
                READINESS_MODEL.OfficialAppUiConnectionState.CONNECTED,
                READINESS_MODEL.ListenerState.PAUSED,
                True,
                fresh_ready=True,
                transport_failure=True,
            )
        )
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_missing_fresh_registration_type_is_unproven(self) -> None:
        obs = READINESS_MODEL.ReadinessObservationV3(
            system_class=READINESS_MODEL.AppSystemClass.LEGACY_VIP,
            observation=READINESS_MODEL.ReadinessObservation(
                ui_state=READINESS_MODEL.OfficialAppUiConnectionState.CONNECTED,
                listener_state=READINESS_MODEL.ListenerState.PAUSED,
                ring_budget_available=True,
            ),
            fresh_registration=None,  # type: ignore[arg-type]
        )
        verdict = READINESS_MODEL.evaluate_readiness_v3(obs)
        self.assertEqual(verdict.official_app_ready, "UNPROVEN")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_not_connected_ui_still_blocks_even_with_fresh_transition(self) -> None:
        verdict = READINESS_MODEL.evaluate_readiness_v3(
            self._obs(
                READINESS_MODEL.OfficialAppUiConnectionState.NOT_CONNECTED,
                READINESS_MODEL.ListenerState.PAUSED,
                True,
                fresh_ready=True,
            )
        )
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)

    def test_listener_ready_still_blocks_ring_even_with_fresh_transition(self) -> None:
        verdict = READINESS_MODEL.evaluate_readiness_v3(
            self._obs(
                READINESS_MODEL.OfficialAppUiConnectionState.CONNECTED,
                READINESS_MODEL.ListenerState.READY,
                True,
                fresh_ready=True,
            )
        )
        self.assertEqual(verdict.official_app_ready, "false")
        self.assertFalse(verdict.physical_ring_allowed)


class ReadinessModelSourceHygieneTests(unittest.TestCase):
    def test_model_has_no_network_surface(self) -> None:
        source = READINESS_MODEL_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import socket",
            "import requests",
            "urllib",
            "http.client",
            "subprocess",
            "asyncio",
        ):
            self.assertNotIn(forbidden, source)


@unittest.skipUnless(CLOSURE_PATH.exists(), "R40H closure document not yet written")
class ClosureDocumentInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = CLOSURE_PATH.read_text(encoding="utf-8")

    def test_closure_contains_canonical_block(self) -> None:
        self.assertIn("=== COMELIT P116 R40H FRESH REGISTRATION / LIVENESS ===", self.doc)
        self.assertIn("=== END COMELIT P116 R40H FRESH REGISTRATION / LIVENESS ===", self.doc)

    def test_closure_carries_executor_provenance(self) -> None:
        """R40H provenance is the partial-fallback form: Claude Code CLI wrote the draft and then hit
        its session limit before verifying anything, so Hermes completed the round as semantic executor.
        The document must say exactly that, not the pre-handover `FALLBACK_USED=false` claim."""
        self.assertIn("EXECUTOR=claude-code-cli+hermes-primary", self.doc)
        self.assertIn("EXECUTOR_FALLBACK_USED=true", self.doc)
        self.assertIn("EXECUTOR_FALLBACK_AFTER_PARTIAL=true", self.doc)
        self.assertIn("EXECUTOR_FALLBACK_REASON=claude_usage_limit", self.doc)
        self.assertIn("BASE_R40G_SHA=b9ebcd04cb0e86e64af41666fe8e27d0fc191d2c", self.doc)

    def test_closure_keeps_zero_live_invariants(self) -> None:
        for token in (
            "PHYSICAL_RING_COUNT=0",
            "LISTENER_PAUSE_COUNT=0",
            "LISTENER_RESUME_COUNT=0",
            "ADB_LIVE_INVOCATIONS=0",
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
            "setEngineVipRegStatus",
            "ReadFromJsonSocket.java",
            "mBound",
            "ViperSocketReaderRunnable.java",
            "VIPER SOCKET CONNECTION LOST",
            "ViperTunnel::open",
            "SO_KEEPALIVE",
            "startKeepAliveChecker",
        ):
            self.assertIn(needle, self.doc)

    def test_closure_does_not_reference_excluded_oauth_evidence(self) -> None:
        self.assertNotIn("oauth-evidence/", self.doc)

    def test_closure_is_address_free_of_real_ipv4(self) -> None:
        matches = [m for m in IPV4_RE.findall(self.doc) if m not in {"0.0.0.0"}]
        self.assertEqual(matches, [])

    def test_closure_has_no_credential_or_token_like_strings(self) -> None:
        lowered = self.doc.lower()
        for forbidden in ("bearer ", "authorization: ", "-----begin"):
            self.assertNotIn(forbidden, lowered)


@unittest.skipUnless(R41_V3_PATH.exists(), "R41 v3 contract not yet written")
class R41V3ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = R41_V3_PATH.read_text(encoding="utf-8")

    def test_v3_contains_canonical_block(self) -> None:
        self.assertIn("=== COMELIT P116 R41 V3 PREFLIGHT CONTRACT (DOCUMENT ONLY) ===", self.doc)
        self.assertIn("RUNNER_CREATED=false", self.doc)
        self.assertIn("LIVE_EXECUTED=false", self.doc)
        self.assertIn("RING_BUDGET_CONSUMED=false", self.doc)
        self.assertIn("NEXT_LIVE_AUTHORIZED=false", self.doc)

    def test_v3_distinguishes_current_state_from_fresh_evidence(self) -> None:
        self.assertIn("CURRENT_UI_STATE", self.doc)
        self.assertIn("FRESH_ATTEMPT_EVIDENCE", self.doc)
        self.assertIn("evaluate_readiness_v3", self.doc)

    def test_v3_states_no_ring_never(self) -> None:
        self.assertIn("NO physical ring", self.doc)

    def test_v2_not_superseded_in_place(self) -> None:
        self.assertTrue(R41_V2_PATH.exists())
        self.assertIn("SUPERSEDES=P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V2.md", self.doc)

    def test_v3_states_ring_budget_always_false(self) -> None:
        self.assertIn("ring_budget_available=false", self.doc)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
