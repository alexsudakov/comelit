from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "p13_hermes_ct120_dispatch.sh"


class HermesCt120DispatchSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_only_two_fixed_modes_are_exposed(self) -> None:
        self.assertIn("readiness)", self.source)
        self.assertIn("observed-open)", self.source)
        self.assertIn("P13_HERMES_CT120_DISPATCH_ALLOWED=readiness|observed-open", self.source)
        self.assertNotIn("eval ", self.source)
        self.assertNotIn("bash -c", self.source)
        self.assertNotIn("sh -c", self.source)

    def test_no_caller_controlled_target_or_operation_identity(self) -> None:
        forbidden = [
            "--target-fingerprint",
            "--operation-id",
            "TARGET_FINGERPRINT=",
            "OPERATION_ID=",
            "PAYLOAD_FILE=",
            "WRAPPER=",
        ]
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.source)

    def test_readiness_is_non_actuating_and_strips_live_identity(self) -> None:
        self.assertIn("P13_HERMES_CT120_DISPATCH_PHYSICAL_ACTION=false", self.source)
        self.assertIn(
            'exec env -u P13_APPROVAL -u P13_OPERATION_ID bash "$PREFLIGHT"',
            self.source,
        )

    def test_observed_open_requires_exact_external_approval(self) -> None:
        self.assertIn(
            "APPROVAL_PHRASE=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST",
            self.source,
        )
        self.assertIn('[[ $# -eq 2 && "${2:-}" == "$APPROVAL_PHRASE" ]]', self.source)
        self.assertIn("P13_HERMES_CT120_DISPATCH_APPROVAL=REQUIRED", self.source)
        self.assertIn("P13_HERMES_CT120_DISPATCH_APPROVAL=GRANTED", self.source)

    def test_observed_open_has_exactly_one_gate_handoff_and_no_retry_loop(self) -> None:
        self.assertEqual(self.source.count('exec bash "$GATE" "$ACTION_PHRASE"'), 1)
        self.assertNotIn("while ", self.source)
        self.assertNotIn("until ", self.source)
        self.assertNotIn("retry", self.source.lower())

    def test_action_capable_children_are_blob_pinned(self) -> None:
        self.assertIn(
            "EXPECTED_PREFLIGHT_BLOB=302ebda51439bdfe8b09782e80b0cd531daad237",
            self.source,
        )
        self.assertIn(
            "EXPECTED_GATE_BLOB=f1e40090b6dc458e90a7e662eee2d20d880f2d4d",
            self.source,
        )
        self.assertIn("P13_HERMES_CT120_DISPATCH_PREFLIGHT_IDENTITY=FAIL", self.source)
        self.assertIn("P13_HERMES_CT120_DISPATCH_GATE_IDENTITY=FAIL", self.source)

    def test_dispatch_does_not_reset_consumed_gate(self) -> None:
        self.assertNotIn("hermes-observed-acceptance-v1.state", self.source)
        self.assertNotIn("rm -f", self.source)
        self.assertNotIn("unlink", self.source)


if __name__ == "__main__":
    unittest.main()
