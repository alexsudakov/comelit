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


if __name__ == "__main__":
    unittest.main()
