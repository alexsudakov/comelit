from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

from entrance_p95_compile_declarations_transform import transform


class P95CompileDeclarationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = (
            ROOT
            / "safety-poc"
            / "research"
            / "door"
            / "v1_5_7"
            / "comelit-v4-persistent-ctpp-door.c"
        )
        cls.candidate = transform(source.read_text(encoding="utf-8"))

    def test_timeout_callback_declared_before_tx_completion_use(self) -> None:
        declaration = "static gboolean p95_device_0002_timeout_cb(gpointer data);"
        self.assertIn(declaration, self.candidate)
        self.assertLess(
            self.candidate.index(declaration),
            self.candidate.index("static void\np12_tx_completed(P12TxKind kind)"),
        )

    def test_frame_handler_declared_before_post_uaut_use(self) -> None:
        declaration_start = "static gboolean p95_handle_device_0002(\n"
        self.assertIn(declaration_start, self.candidate)
        self.assertLess(
            self.candidate.index(declaration_start),
            self.candidate.index("p12_process_post_uaut"),
        )

    def test_protocol_contract_is_unchanged(self) -> None:
        self.assertIn("P80_DEVICE_0002_GATE_ARMED=true", self.candidate)
        self.assertIn("P80_DEVICE_0002_ACK_SENT=PASS", self.candidate)
        self.assertIn("P80_DEVICE_0002_GATE=PASS", self.candidate)
        self.assertIn("P78_SECOND_CTPP_OPEN=false", self.candidate)
        self.assertIn("P80_DOOR_SIGNAL_ENTRYPOINT=false", self.candidate)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)


if __name__ == "__main__":
    unittest.main()
