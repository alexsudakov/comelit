#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "safety-poc" / "research" / "media" / "v1" / "ct120_build_p80_haos_media_helper.sh"


def _builder_function(name: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"\n{name}\(\) \{{\n.*?\n\}}\n\nsummary\(\)", text, re.DOTALL)
    if not match:
        raise AssertionError(f"{name} function not found")
    return match.group(0).rsplit("\n\nsummary()", 1)[0].strip()


class P116BuildProvenanceGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.resolve_function = _builder_function("p80_rootfs_library_realpath")

    def _resolve_lib(self, rootfs: Path, needed: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                "-eu",
                "-o",
                "pipefail",
                "-c",
                self.resolve_function + '\np80_rootfs_library_realpath "$1" "$2"',
                "bash",
                str(rootfs),
                needed,
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_library_gate_accepts_soname_symlink_and_compares_resolved_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rootfs = base / "rootfs"
            packaged = base / "repo" / "custom_components" / "comelit" / "native" / "lib"
            rootfs_usr_lib = rootfs / "usr" / "lib"
            packaged.mkdir(parents=True)
            rootfs_usr_lib.mkdir(parents=True)

            needed = "libglib-2.0.so.0"
            real_name = "libglib-2.0.so.0.8801.0"
            content = b"same pinned bytes\n"
            (rootfs_usr_lib / real_name).write_bytes(content)
            (packaged / needed).write_bytes(content)
            os.symlink(real_name, rootfs_usr_lib / needed)

            result = self._resolve_lib(rootfs, needed)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(os.readlink(rootfs_usr_lib / needed), real_name)
            self.assertEqual(Path(result.stdout.strip()).resolve(), (rootfs_usr_lib / real_name).resolve())
            self.assertEqual((packaged / needed).read_bytes(), Path(result.stdout.strip()).read_bytes())

    def test_library_gate_rejects_real_content_mismatch_after_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rootfs = base / "rootfs"
            packaged = base / "repo" / "custom_components" / "comelit" / "native" / "lib"
            rootfs_usr_lib = rootfs / "usr" / "lib"
            packaged.mkdir(parents=True)
            rootfs_usr_lib.mkdir(parents=True)

            needed = "libnice.so.10"
            real_name = "libnice.so.10.22.0"
            (rootfs_usr_lib / real_name).write_bytes(b"rootfs bytes\n")
            (packaged / needed).write_bytes(b"packaged bytes\n")
            os.symlink(real_name, rootfs_usr_lib / needed)

            result = self._resolve_lib(rootfs, needed)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual((packaged / needed).read_bytes(), Path(result.stdout.strip()).read_bytes())
            self.assertIn('reason=content_mismatch', self.script)
            self.assertIn('cmp -s "$packaged" "$rootfs_lib"', self.script)

    def test_library_gate_rejects_broken_and_outside_rootfs_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rootfs = base / "rootfs"
            rootfs_usr_lib = rootfs / "usr" / "lib"
            rootfs_usr_lib.mkdir(parents=True)

            os.symlink("missing-target.so", rootfs_usr_lib / "libgobject-2.0.so.0")
            broken = self._resolve_lib(rootfs, "libgobject-2.0.so.0")
            self.assertNotEqual(broken.returncode, 0)

            outside = base / "outside-libnice.so"
            outside.write_bytes(b"outside\n")
            os.symlink(outside, rootfs_usr_lib / "libnice.so.10")
            escaped = self._resolve_lib(rootfs, "libnice.so.10")
            self.assertNotEqual(escaped.returncode, 0)

            self.assertIn('reason=rootfs_lib_unresolved', self.script)
            self.assertIn('"$rootfs_real"/*)', self.script)

    def test_builder_repo_branch_and_exact_sha_are_env_driven(self) -> None:
        self.assertIn("REPO=${REPO:-/root/comelit-door-diag-repo}", self.script)
        self.assertIn("BRANCH=${BRANCH:-fix/p116-ha-stream-rtp-bridge}", self.script)
        self.assertIn("P80_BUILD_EXPECTED_SHA=${P80_BUILD_EXPECTED_SHA:-}", self.script)
        self.assertIn("P80_BUILD_ALLOW_DETACHED=${P80_BUILD_ALLOW_DETACHED:-0}", self.script)
        self.assertNotRegex(self.script, r"(?m)^REPO=/")
        self.assertNotRegex(self.script, r"(?m)^BRANCH=feature/")
        self.assertIn('[ "$REPO_HEAD" = "$P80_BUILD_EXPECTED_SHA" ]', self.script)
        self.assertIn('[ "$P80_BUILD_ALLOW_DETACHED" = "1" ]', self.script)
        self.assertIn("P80_BUILD_BRANCH_GATE=SKIPPED_DETACHED", self.script)
        self.assertIn("P80_BUILD_EXPECTED_SHA_REQUIRED_FOR_DETACHED=FAIL", self.script)

    def test_default_build_transform_is_p106_composition_and_env_overrideable(self) -> None:
        default = (
            "safety-poc/research/media/v1/"
            "entrance_p106_teardown_state_classification_transform.py"
        )
        old_p80 = (
            "TRANSFORM_REL=safety-poc/research/media/v1/"
            "entrance_p80_ha_media_runtime_transform.py"
        )
        self.assertIn(f"P80_BUILD_TRANSFORM=${{P80_BUILD_TRANSFORM:-{default}}}", self.script)
        self.assertNotIn(old_p80, self.script)
        self.assertIn('python3 "$REPO/$P80_BUILD_TRANSFORM"', self.script)
        self.assertIn('[ -f "$REPO/$P80_BUILD_TRANSFORM" ]', self.script)
        self.assertIn("P80_BUILD_TRANSFORM=$P80_BUILD_TRANSFORM", self.script)

        result = subprocess.run(
            [
                "bash",
                "-eu",
                "-c",
                (
                    "P80_BUILD_TRANSFORM=${P80_BUILD_TRANSFORM:-"
                    + default
                    + "}; printf '%s' \"$P80_BUILD_TRANSFORM\""
                ),
            ],
            check=False,
            env={**os.environ, "P80_BUILD_TRANSFORM": "custom/transform.py"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "custom/transform.py")

    def test_expected_source_sha_gate_is_env_driven_and_fail_closed(self) -> None:
        self.assertIn("P80_BUILD_EXPECTED_SOURCE_SHA=${P80_BUILD_EXPECTED_SOURCE_SHA:-}", self.script)
        self.assertIn("GENERATED_SOURCE_SHA256=\"$(sha256sum \"$GENERATED\" | awk '{print $1}')\"", self.script)
        self.assertIn('echo "GENERATED_SOURCE_SHA256=$GENERATED_SOURCE_SHA256"', self.script)
        self.assertIn('if [ -n "$P80_BUILD_EXPECTED_SOURCE_SHA" ]; then', self.script)
        self.assertIn(
            '[ "$GENERATED_SOURCE_SHA256" = "$P80_BUILD_EXPECTED_SOURCE_SHA" ]',
            self.script,
        )
        self.assertIn("P80_BUILD_EXPECTED_SOURCE_SHA_GATE=PASS", self.script)
        self.assertIn(
            "P80_BUILD_EXPECTED_SOURCE_SHA_GATE=FAIL expected=$P80_BUILD_EXPECTED_SOURCE_SHA "
            "actual=$GENERATED_SOURCE_SHA256",
            self.script,
        )
        self.assertLess(
            self.script.index("P80_BUILD_EXPECTED_SOURCE_SHA_GATE=FAIL"),
            self.script.index("=== ALPINE CHROOT BUILD ==="),
        )

    def test_source_gate_and_build_meta_use_selected_generator_provenance(self) -> None:
        transform_call = self.script.index('python3 "$REPO/$P80_BUILD_TRANSFORM"')
        source_sha = self.script.index("GENERATED_SOURCE_SHA256=\"$(sha256sum")
        source_gate = self.script.index("P80_GENERATED_SOURCE_GATE=PASS")
        chroot_build = self.script.index("=== ALPINE CHROOT BUILD ===")
        self.assertLess(transform_call, source_sha)
        self.assertLess(source_sha, source_gate)
        self.assertLess(source_gate, chroot_build)

        for marker in (
            '#define RUN_DIR     "/run/comelit-media"',
            "signal(SIGUSR1, v4_door_signal_handler);",
            "P80_MEDIA_ACTIVE=true",
            "P80_VIDEO_RTP_FORWARDING=PASS",
            "P80_AUDIO_RTP_FORWARDING=PASS",
            "P78_SECOND_CTPP_OPEN=false",
        ):
            self.assertIn(marker, self.script)

        meta_append = self.script.index('echo "NATIVE_BINARY_SHA256=$CANDIDATE_SHA"')
        meta_print = self.script.index('cat "$META"')
        self.assertLess(meta_append, meta_print)
        for field in (
            "P80_BUILD_TRANSFORM=$P80_BUILD_TRANSFORM",
            "P80_BUILD_EXPECTED_SOURCE_SHA=$P80_BUILD_EXPECTED_SOURCE_SHA",
            "GENERATED_SOURCE_SHA256=$GENERATED_SOURCE_SHA256",
            "NATIVE_BINARY_SHA256=$CANDIDATE_SHA",
        ):
            self.assertIn(f'echo "{field}"', self.script)


if __name__ == "__main__":
    unittest.main()
