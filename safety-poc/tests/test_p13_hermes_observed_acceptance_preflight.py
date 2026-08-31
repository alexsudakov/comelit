from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "p13_hermes_observed_acceptance_preflight.sh"


class HermesObservedAcceptancePreflightSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_preflight_never_calls_live_entrypoint(self) -> None:
        self.assertNotIn('bash "$GATE"', self.source)
        self.assertNotIn('bash "$INNER"', self.source)
        self.assertNotIn('bash "$RUNNER"', self.source)
        self.assertIn('bash "$PREFLIGHT"', self.source)

    def test_live_approval_identity_is_removed_from_child(self) -> None:
        self.assertIn(
            'env -u P13_APPROVAL -u P13_OPERATION_ID bash "$PREFLIGHT"',
            self.source,
        )

    def test_action_capable_sources_are_pinned(self) -> None:
        self.assertIn(
            "EXPECTED_GATE_BLOB=f1e40090b6dc458e90a7e662eee2d20d880f2d4d",
            self.source,
        )
        self.assertIn(
            "EXPECTED_INNER_BLOB=d0a640bd2cb06bf108e7edfb26b8e35a7cbfc3fe",
            self.source,
        )
        self.assertIn(
            "EXPECTED_RUNNER_BLOB=d9c13d28aba66b44b27402c026ddebb89419cba4",
            self.source,
        )

    def test_unused_gate_is_required(self) -> None:
        self.assertIn('if [[ -e "$STATE_FILE" ]]', self.source)
        self.assertIn("P13_HERMES_OBSERVED_GATE_UNUSED=false", self.source)
        self.assertIn("P13_HERMES_OBSERVED_GATE_UNUSED=true", self.source)

    def test_readiness_requires_non_actuating_markers(self) -> None:
        required = [
            "P13_NON_ACTUATING_PREFLIGHT=PASS",
            "READONLY_TRANSPORT_READY=true",
            "P13_ONE_SHOT_MAX_INVOCATIONS=1",
            "P13_AUTO_RETRY_ALLOWED=false",
            "EXPLICIT_LIVE_TEST_APPROVAL=false",
            "LIVE_TEST_READY=false",
            "P13_ACTUATOR_COMMAND_ATTEMPTED=false",
            "PHYSICAL_DOOR_ACTION=false",
            "PHYSICAL_EFFECT_ASSERTED=false",
        ]
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)

    def test_ready_output_stays_unapproved_and_non_actuating(self) -> None:
        self.assertIn("P13_HERMES_OBSERVED_ACCEPTANCE_READY=true", self.source)
        self.assertIn("EXPLICIT_LIVE_TEST_APPROVAL=false", self.source)
        self.assertIn("LIVE_TEST_READY=false", self.source)
        self.assertIn("SEND_ARMED_REACHED=false", self.source)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", self.source)
        self.assertIn("PHYSICAL_EFFECT_ASSERTED=false", self.source)
        self.assertNotIn("PHYSICAL_EFFECT_ASSERTED=true", self.source)


if __name__ == "__main__":
    unittest.main()
