from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "p13_hermes_observed_acceptance.sh"


class HermesObservedAcceptanceSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_exact_action_phrase_is_required(self) -> None:
        self.assertIn("ACTION_PHRASE=OPEN_72K4_3_ONCE", self.source)
        self.assertIn('[[ "${1:-}" == "$ACTION_PHRASE" && $# -eq 1 ]]', self.source)

    def test_gate_is_consumed_before_live_entrypoint(self) -> None:
        consume = self.source.index("CONSUMED_BEFORE_LIVE_ENTRYPOINT")
        live_call = self.source.index('bash "$INNER" "$ACTION_PHRASE"')
        self.assertLess(consume, live_call)
        self.assertIn("os.fsync(fd)", self.source)
        self.assertIn("os.fsync(parent)", self.source)

    def test_duplicate_gate_state_rejects_without_live_call_branch(self) -> None:
        guard = re.search(
            r'if \[\[ -e "\$STATE_FILE" \]\]; then(?P<body>.*?)fi',
            self.source,
            flags=re.S,
        )
        self.assertIsNotNone(guard)
        body = guard.group("body")
        self.assertIn("P13_HERMES_OBSERVED_GATE_CONSUMED=true", body)
        self.assertIn("P13_HERMES_OBSERVED_RESEND_ALLOWED=false", body)
        self.assertIn("exit 76", body)
        self.assertNotIn("$INNER", body)

    def test_inner_entrypoint_identity_is_pinned(self) -> None:
        self.assertIn(
            "EXPECTED_INNER_BLOB=d0a640bd2cb06bf108e7edfb26b8e35a7cbfc3fe",
            self.source,
        )
        self.assertIn('git -C "$REPO_ROOT" hash-object "$INNER"', self.source)
        self.assertIn("P13_HERMES_OBSERVED_INNER_IDENTITY=FAIL", self.source)

    def test_only_one_live_capable_inner_invocation_exists(self) -> None:
        self.assertEqual(self.source.count('bash "$INNER" "$ACTION_PHRASE"'), 1)
        self.assertNotRegex(self.source, r"\b(for|while|until)\b.*\$INNER")
        self.assertIn("P13_HERMES_OBSERVED_AUTO_RETRY_ALLOWED=false", self.source)
        self.assertIn("P13_HERMES_OBSERVED_RESEND_ALLOWED=false", self.source)

    def test_gate_has_no_reset_or_remove_path(self) -> None:
        self.assertNotRegex(self.source, r"\brm\b[^\n]*\$STATE_FILE")
        self.assertNotRegex(self.source, r"\bunlink\b[^\n]*\$STATE_FILE")
        self.assertNotIn("RESET_GATE", self.source)

    def test_physical_effect_is_not_asserted(self) -> None:
        self.assertNotIn("PHYSICAL_EFFECT_ASSERTED=true", self.source)


if __name__ == "__main__":
    unittest.main()
