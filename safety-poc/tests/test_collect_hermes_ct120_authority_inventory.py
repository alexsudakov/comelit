from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect_hermes_ct120_authority_inventory.sh"


class HermesCt120AuthorityInventorySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_collector_is_read_only(self) -> None:
        forbidden = [
            "git fetch",
            "git checkout",
            "git reset",
            "git switch",
            "systemctl restart",
            "systemctl reload",
            "chmod ",
            "chown ",
            "install ",
            "touch ",
            "mkdir ",
            "rm -",
            "mv ",
            "cp ",
            "sed -i",
        ]
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.source)

    def test_collector_never_calls_comelit_transport_or_live_gate(self) -> None:
        forbidden = [
            'bash "$GATE"',
            "p13_hermes_observed_acceptance.sh OPEN_72K4_3_ONCE",
            "p13_hermes_one_shot.sh OPEN_72K4_3_ONCE",
            "p13_one_shot_physical_runner.sh",
            "P13_APPROVAL=",
        ]
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.source)

    def test_key_material_is_not_emitted(self) -> None:
        self.assertIn("AUTHORIZED_KEY_LINE_SHA256", self.source)
        self.assertIn("AUTHORIZED_KEY_FORCED_COMMAND", self.source)
        self.assertIn("SSH_KEY_MATERIAL_EMITTED=false", self.source)
        self.assertNotIn("print(f'PUBLIC_KEY=", self.source)

    def test_inventory_covers_authority_layers(self) -> None:
        required = [
            "RESTRICTED_OPERATOR_PRESENT",
            "HERMES_COMELIT_DISPATCH",
            "SSHD EFFECTIVE AUTHORIZATION",
            "AUTHORIZED KEYS FORCED COMMANDS",
            "SUDO AUTHORIZATION",
            "SYSTEMD BROKER CANDIDATES",
            "CT120_REPO_HEAD",
            "REPO_FILE_BLOB",
        ]
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_terminal_safety_markers_are_explicit(self) -> None:
        required = [
            "NETWORK_DOOR_ACTION_PERFORMED=false",
            "PHYSICAL_DOOR_ACTION=false",
            "SEND_ARMED_REACHED=false",
            "P13_ACTUATOR_COMMAND_ATTEMPTED=false",
            "P13_PHYSICAL_EFFECT_ASSERTED=false",
            "RUNTIME_AUTHORITY_CHANGED=false",
            "HERMES_CT120_AUTHORITY_INVENTORY_COMPLETE=true",
        ]
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)


if __name__ == "__main__":
    unittest.main()
