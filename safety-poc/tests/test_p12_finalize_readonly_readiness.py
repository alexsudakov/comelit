import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p12_finalize_readonly_readiness.py"
spec = importlib.util.spec_from_file_location("p12_finalize_readonly_readiness", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def marker_text(gates):
    return "\n".join(f"{marker}={expected}" for marker, expected in gates) + "\n"


class P12FinalizeReadonlyReadinessTests(unittest.TestCase):
    def setUp(self):
        self.repository = marker_text(module.REPOSITORY_GATES)
        self.live = marker_text(module.READONLY_GATES) + "P12_READONLY_LIVE_GATES=PASS\n"

    def test_complete_independent_evidence_opens_readonly_only(self):
        _, repository_ready, readonly_ready, live_ready = module.finalize(self.repository, self.live)
        self.assertTrue(repository_ready)
        self.assertTrue(readonly_ready)
        self.assertFalse(live_ready)

    def test_missing_repository_gate_fails_closed(self):
        first_marker = module.REPOSITORY_GATES[0][0]
        repository = "\n".join(
            line for line in self.repository.splitlines() if not line.startswith(first_marker + "=")
        )
        with self.assertRaises(RuntimeError):
            module.finalize(repository, self.live)

    def test_missing_target_binding_fails_closed(self):
        live = self.live.replace("TARGET_BINDING_VERIFIED=PASS\n", "")
        with self.assertRaises(RuntimeError):
            module.finalize(self.repository, live)

    def test_any_actuation_or_physical_marker_fails_closed(self):
        for unsafe in (
            "ACTUATION_TRANSPORT_IMPLEMENTED=true",
            "EXPLICIT_LIVE_TEST_APPROVAL=true",
            "PHYSICAL_DOOR_ACTION=true",
            "PHYSICAL_EFFECT_ASSERTED=true",
            "ACTUATOR_COMMAND_ATTEMPTED=true",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(RuntimeError):
                    module.finalize(self.repository, self.live + unsafe + "\n")

    def test_report_is_owner_only_and_never_opens_live_test_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "final.txt"
            module.write_report(output, self.repository, self.live)
            text = output.read_text(encoding="utf-8")
            self.assertIn("REPOSITORY_READY=true", text)
            self.assertIn("READONLY_TRANSPORT_READY=true", text)
            self.assertIn("LIVE_TEST_READY=false", text)
            self.assertIn("ACTUATION_TRANSPORT_IMPLEMENTED=false", text)
            self.assertIn("PHYSICAL_DOOR_ACTION=false", text)
            self.assertIn("P12_READONLY_FINALIZATION=PASS", text)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
