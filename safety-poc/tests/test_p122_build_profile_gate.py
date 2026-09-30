#!/usr/bin/env python3
"""Offline tests for the CT120 media build profile marker gate."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
GATE = MEDIA / "p80_media_build_profile_gate.sh"
BUILDER = MEDIA / "ct120_build_p80_haos_media_helper.sh"

sys.path.insert(0, str(MEDIA))
import entrance_p122_on_demand_media_door_transform as p122  # noqa: E402


EXPECTED_P122_GENERATED_SHA256 = (
    "ec39399ade72cb4800131d5a0995e0053a3f9af22560fd40894af057994d6d47"
)

LEGACY_SOURCE_MARKERS = (
    '#define RUN_DIR     "/run/comelit-media"',
    "P80_MEDIA_ACTIVE=true",
    "P80_VIDEO_RTP_FORWARDING=PASS",
    "P80_AUDIO_RTP_FORWARDING=PASS",
    "P78_SECOND_CTPP_OPEN=false",
)

LEGACY_BINARY_MARKERS = (
    "/run/comelit-media",
    "P80_MEDIA_ACTIVE=true",
    "P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT",
    "P80_MEDIA_AUTO_CLOSE_3000MS=false",
    "P80_DOOR_SIGNAL_ENTRYPOINT=false",
    "P80_VIDEO_RTP_FORWARDING=PASS",
    "P80_AUDIO_RTP_FORWARDING=PASS",
    "P80_WRAPPER_PROFILE_MISMATCH=true",
    "P78_SECOND_CTPP_OPEN=false",
    "ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false",
)

P122_SOURCE_MARKERS = (
    "P80_MEDIA_ACTIVE=true",
    "P80_DOOR_SIGNAL_ENTRYPOINT=true",
    "P122_ONDEMAND_DOOR_SIGNAL_INSTALLED=true",
    "P122_ONDEMAND_DOOR_PROFILE=ACTIVE_MEDIA_SINGLE",
    "P122_ONDEMAND_DOOR_PATH=ACTIVE_MEDIA_SINGLE",
    "P122_ONDEMAND_DOOR_SENT=true",
    "P122_ONDEMAND_DOOR_WRITE_COUNT=1",
    "P122_ONDEMAND_DOOR_RESULT=%s",
    "P122_ONDEMAND_DOOR_REJECT_GATE=%s",
    "P122_ONDEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
    "P122_ONDEMAND_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
    "P78_SECOND_CTPP_OPEN=false",
)

P122_BINARY_MARKERS = (
    "/run/comelit-media",
    "P80_MEDIA_ACTIVE=true",
    "P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT",
    "P80_DOOR_SIGNAL_ENTRYPOINT=true",
    "P122_ONDEMAND_DOOR_SIGNAL_INSTALLED=true",
    "P122_ONDEMAND_DOOR_PROFILE=ACTIVE_MEDIA_SINGLE",
    "P122_ONDEMAND_DOOR_PATH=ACTIVE_MEDIA_SINGLE",
    "P122_ONDEMAND_DOOR_SENT=true",
    "P122_ONDEMAND_DOOR_WRITE_COUNT=1",
    "P122_ONDEMAND_DOOR_RESULT=%s",
    "P122_ONDEMAND_DOOR_REJECT_GATE=%s",
    "P122_ONDEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
    "P122_ONDEMAND_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
    "P80_VIDEO_RTP_FORWARDING=PASS",
    "P80_AUDIO_RTP_FORWARDING=PASS",
    "P78_SECOND_CTPP_OPEN=false",
)


def _without_marker(text: str, marker: str) -> str:
    mutated = text.replace(marker, "REMOVED_PROFILE_GATE_MARKER")
    if mutated == text:
        raise AssertionError(f"fixture did not contain marker: {marker}")
    return mutated


class P122BuildProfileGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.builder = BUILDER.read_text(encoding="utf-8")
        cls.p122_generated = p122.transform(SOURCE.read_text(encoding="utf-8"))
        cls.p122_strings = cls.p122_generated
        cls.legacy_source = "\n".join(LEGACY_SOURCE_MARKERS) + "\n"
        cls.legacy_strings = "\n".join(LEGACY_BINARY_MARKERS) + "\n"

    def _run_gate(
        self,
        *,
        profile: str,
        source_text: str | None = None,
        strings_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="p122-profile-gate-") as tmp:
            args = ["bash", str(GATE), "--profile", profile]
            if source_text is not None:
                source_path = Path(tmp) / "generated.c"
                source_path.write_text(source_text, encoding="utf-8")
                args.extend(["--generated-source", str(source_path)])
            if strings_text is not None:
                strings_path = Path(tmp) / "candidate.strings"
                strings_path.write_text(strings_text, encoding="utf-8")
                args.extend(["--strings-file", str(strings_path)])
            return subprocess.run(
                args,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

    def assertGatePasses(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def assertGateFailsOn(
        self, result: subprocess.CompletedProcess[str], marker: str
    ) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"marker={marker}", result.stderr + result.stdout)

    def test_legacy_profile_passes_and_each_legacy_binary_marker_is_required(self) -> None:
        self.assertGatePasses(
            self._run_gate(
                profile="LEGACY",
                source_text=self.legacy_source,
                strings_text=self.legacy_strings,
            )
        )

        for marker in LEGACY_BINARY_MARKERS:
            with self.subTest(marker=marker):
                self.assertGateFailsOn(
                    self._run_gate(
                        profile="LEGACY",
                        source_text=self.legacy_source,
                        strings_text=_without_marker(self.legacy_strings, marker),
                    ),
                    marker,
                )

    def test_legacy_profile_keeps_existing_source_contract(self) -> None:
        for marker in LEGACY_SOURCE_MARKERS:
            with self.subTest(marker=marker):
                self.assertGateFailsOn(
                    self._run_gate(
                        profile="LEGACY",
                        source_text=_without_marker(self.legacy_source, marker),
                        strings_text=self.legacy_strings,
                    ),
                    marker,
                )

    def test_p122_profile_passes_with_real_generated_lineage_fixture(self) -> None:
        self.assertEqual(
            hashlib.sha256(self.p122_generated.encode("utf-8")).hexdigest(),
            EXPECTED_P122_GENERATED_SHA256,
        )
        for marker in P122_SOURCE_MARKERS + P122_BINARY_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.p122_generated)

        result = self._run_gate(
            profile="P122",
            source_text=self.p122_generated,
            strings_text=self.p122_strings,
        )

        self.assertGatePasses(result)
        self.assertIn("PROFILE_SOURCE_GATE=PASS profile=P122", result.stdout)
        self.assertIn("PROFILE_BINARY_GATE=PASS profile=P122", result.stdout)

    def test_p122_profile_requires_each_p122_source_marker(self) -> None:
        for marker in P122_SOURCE_MARKERS:
            with self.subTest(marker=marker):
                self.assertGateFailsOn(
                    self._run_gate(
                        profile="P122",
                        source_text=_without_marker(self.p122_generated, marker),
                        strings_text=self.p122_strings,
                    ),
                    marker,
                )

    def test_p122_profile_requires_each_p122_binary_marker(self) -> None:
        for marker in P122_BINARY_MARKERS:
            with self.subTest(marker=marker):
                self.assertGateFailsOn(
                    self._run_gate(
                        profile="P122",
                        source_text=self.p122_generated,
                        strings_text=_without_marker(self.p122_strings, marker),
                    ),
                    marker,
                )

    def test_p122_profile_rejects_legacy_false_marker_in_source_or_strings(self) -> None:
        marker = "P80_DOOR_SIGNAL_ENTRYPOINT=false"
        self.assertGateFailsOn(
            self._run_gate(
                profile="P122",
                source_text=self.p122_generated + f"\n{marker}\n",
                strings_text=self.p122_strings,
            ),
            marker,
        )
        self.assertGateFailsOn(
            self._run_gate(
                profile="P122",
                source_text=self.p122_generated,
                strings_text=self.p122_strings + f"\n{marker}\n",
            ),
            marker,
        )

    def test_wrong_profile_marker_combinations_fail(self) -> None:
        self.assertGateFailsOn(
            self._run_gate(
                profile="LEGACY",
                source_text=self.p122_generated,
                strings_text=self.p122_strings,
            ),
            "P80_DOOR_SIGNAL_ENTRYPOINT=false",
        )
        self.assertGateFailsOn(
            self._run_gate(
                profile="P122",
                source_text=self.legacy_source,
                strings_text=self.legacy_strings,
            ),
            "P80_DOOR_SIGNAL_ENTRYPOINT=true",
        )

    def test_unknown_profile_fails_closed(self) -> None:
        result = self._run_gate(
            profile="INVALID",
            source_text=self.legacy_source,
            strings_text=self.legacy_strings,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("P80_BUILD_PROFILE=INVALID value=INVALID", result.stderr)

    def test_builder_profile_default_is_legacy_and_delegates_marker_gate(self) -> None:
        self.assertIn("P80_BUILD_PROFILE=${P80_BUILD_PROFILE:-LEGACY}", self.builder)
        self.assertIn("P80_BUILD_PROFILE_GATE=safety-poc/research/media/v1/p80_media_build_profile_gate.sh", self.builder)
        self.assertIn('case "$P80_BUILD_PROFILE" in', self.builder)
        self.assertIn('echo "P80_BUILD_PROFILE=$P80_BUILD_PROFILE"', self.builder)
        self.assertIn('--profile "$P80_BUILD_PROFILE"', self.builder)
        self.assertNotIn("'P80_DOOR_SIGNAL_ENTRYPOINT=false' \\", self.builder)
        self.assertNotIn("P80_MEDIA_AUTO_CLOSE_3000MS=false", self.builder)

        result = subprocess.run(
            [
                "bash",
                "-eu",
                "-c",
                'P80_BUILD_PROFILE=${P80_BUILD_PROFILE:-LEGACY}; printf "%s" "$P80_BUILD_PROFILE"',
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "LEGACY")


if __name__ == "__main__":
    unittest.main()
