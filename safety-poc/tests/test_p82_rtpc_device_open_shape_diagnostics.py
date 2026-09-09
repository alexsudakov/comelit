#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
SOURCE = ROOT / "safety-poc" / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
sys.path.insert(0, str(MEDIA))

from entrance_p82_rtpc_device_open_shape_transform import report, transform  # noqa: E402


class P82RtpcDeviceOpenShapeDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = transform(SOURCE.read_text(encoding="utf-8"))

    def test_failure_path_emits_only_safe_structural_shape_markers(self) -> None:
        for marker in (
            "P80_RTPC_DEVICE_OPEN_BODY_LEN=",
            "P80_RTPC_DEVICE_OPEN_MAGIC_MATCH=",
            "P80_RTPC_DEVICE_OPEN_OPCODE=",
            "P80_RTPC_DEVICE_OPEN_DECLARED_LEN=",
            "P80_RTPC_DEVICE_OPEN_TAG_MATCH=",
            "P80_RTPC_DEVICE_OPEN_TRAILER_PRESENT=",
            "P80_RTPC_DEVICE_OPEN_TRAILER=",
            "P80_RTPC_DEVICE_OPEN_VALIDATION_STATUS=",
            'p78_fail_rtpc("P78_RTPC_DEVICE_OPEN=FAIL")',
        ):
            self.assertIn(marker, self.generated)

    def test_diagnostics_do_not_emit_target_or_raw_payload(self) -> None:
        diagnostic_start = self.generated.index("P80_RTPC_DEVICE_OPEN_BODY_LEN=")
        diagnostic_end = self.generated.index(
            'p78_fail_rtpc("P78_RTPC_DEVICE_OPEN=FAIL")', diagnostic_start
        )
        diagnostic = self.generated[diagnostic_start:diagnostic_end]
        self.assertNotIn("target_id", diagnostic)
        self.assertNotIn("device_open_target", diagnostic)
        self.assertNotIn("%02x", diagnostic)
        self.assertNotIn("base64", diagnostic.lower())

    def test_validation_and_signaling_are_not_changed(self) -> None:
        self.assertIn(
            "status = p76_observe_device_open(&p78_rtpc_runtime, body, body_len);",
            self.generated,
        )
        self.assertIn("P78_RTPC_OPEN_1_SENT=PASS", self.generated)
        self.assertIn("P78_RTPC_OPEN_2_SENT=PASS", self.generated)
        self.assertIn("P78_SECOND_CTPP_OPEN=false", self.generated)
        self.assertIn("P80_MEDIA_ACTIVE=true", self.generated)

    def test_report_is_offline_and_non_actuating(self) -> None:
        text = report()
        self.assertIn("P82_VALIDATION_CHANGED=false", text)
        self.assertIn("P82_SIGNALING_CHANGED=false", text)
        self.assertIn("P82_TARGET_ID_EMITTED=false", text)
        self.assertIn("P82_RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("P82_NETWORK_IO_PERFORMED=false", text)
        self.assertIn("P82_CANDIDATE_EXECUTED=false", text)
        self.assertIn("DOOR_ACTION_SENT=false", text)


if __name__ == "__main__":
    unittest.main()
