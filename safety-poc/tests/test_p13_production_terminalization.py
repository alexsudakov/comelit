from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

LIVE_PATHS = (
    ROOT / "deploy" / "p13_g1b_production_validation_gate.sh",
    ROOT / "deploy" / "p13_g1b_production_validation_runner.sh",
    ROOT / "scripts" / "install_p13_g1b_hermes_authority.sh",
)

INSTALLER = ROOT / "deploy" / "install_p13_production_release.sh"
DISPATCH = ROOT / "deploy" / "p13_production_runtime_dispatch.sh"
DOC = ROOT / "docs" / "P13_PRODUCTION_HARDENING.md"


class P13ProductionTerminalizationTests(unittest.TestCase):
    def test_temporary_g1b_live_sources_are_absent(self):
        for path in LIVE_PATHS:
            self.assertFalse(
                path.exists(),
                f"temporary G1B live source retained: {path}",
            )

    def test_no_g1b_live_approval_surface_in_deploy_or_scripts(self):
        approval = (
            "I_APPROVE_P13_G1B_"
            "IMMUTABLE_PRODUCTION_DOOR_TEST"
        )

        for directory in (ROOT / "deploy", ROOT / "scripts"):
            for path in directory.rglob("*"):
                if not path.is_file():
                    continue
                text = path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
                self.assertNotIn(
                    approval,
                    text,
                    f"G1B live approval retained in {path}",
                )

    def test_final_release_schema_has_no_g1b_live_validation_flag(self):
        text = INSTALLER.read_text(encoding="utf-8")

        self.assertNotIn(
            "P13_G1B_VALIDATION_SCHEMA",
            text,
        )

    def test_production_dispatcher_remains_readiness_only(self):
        text = DISPATCH.read_text(encoding="utf-8")

        self.assertIn(
            "P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false",
            text,
        )
        self.assertIn(
            "P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true",
            text,
        )
        self.assertNotIn(
            "p13-g1b",
            text.lower(),
        )

    def test_docs_bind_terminal_g1b_evidence(self):
        text = DOC.read_text(encoding="utf-8")

        self.assertIn(
            "evidence/p13-g1b-opened-20260831T203116Z",
            text,
        )
        self.assertIn(
            "4ce5dedebe9df7e681e38af84f59ae92eafe8c28",
            text,
        )
        self.assertIn(
            "p13-g1b-production-opened-20260831T203116Z.txt",
            text,
        )
        self.assertIn(
            "UNKNOWN_OUTCOME",
            text,
        )
        self.assertIn(
            "Door-specific ACK: `UNPROVEN`",
            text,
        )
        self.assertIn(
            "observed physical acceptance: `PASS`",
            text,
        )

    def test_final_release_manifest_binds_frozen_g1b_evidence(self):
        text = INSTALLER.read_text(encoding="utf-8")

        required = (
            "4ce5dedebe9df7e681e38af84f59ae92eafe8c28",
            "f089fd459af8a0ee3365b86b7cee99e31d8e1e9c",
            "p13-g1b-production-opened-20260831T203116Z.txt",
            "p13-g1b-80de7068-72e5-40db-9e4f-47e1a42d2351",
            "P13_G1B_PROTOCOL_STATE=UNKNOWN_OUTCOME",
            "P13_G1B_DOOR_SPECIFIC_ACK=UNPROVEN",
            "P13_G1B_PHYSICAL_OBSERVATION=OPENED",
            "P13_G1B_OBSERVED_PHYSICAL_ACCEPTANCE=PASS",
            "P13_G1B_GATE_TERMINAL=CONSUMED",
            "P13_G1B_RESEND_ALLOWED=false",
            "P13_G1B_AUTO_RETRY_ALLOWED=false",
            "P13_G1B_TEMPORARY_HERMES_AUTHORITY_RETIRED=true",
        )

        for marker in required:
            self.assertIn(marker, text)

        self.assertNotIn(
            "I_APPROVE_P13_G1B_IMMUTABLE_PRODUCTION_DOOR_TEST",
            text,
        )

    def test_p14_reusable_authority_remains_separate(self):
        text = DOC.read_text(encoding="utf-8")

        self.assertIn(
            "Reusable Door actuation belongs",
            text,
        )
        self.assertIn(
            "to P14",
            text,
        )


if __name__ == "__main__":
    unittest.main()
