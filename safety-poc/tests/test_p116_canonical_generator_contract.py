#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE_REL = Path("safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c")
TRANSFORM_REL = Path(
    "safety-poc/research/media/v1/entrance_p106_teardown_state_classification_transform.py"
)
HISTORICAL_COMMIT = "a54fe39e18c9d97c515a7145d63c4e1ce7fa3afc"
ARCHIVED_P106_SOURCE_SHA256 = "0c15927dbc40bdb1f7c522f063a8a2f38c557f9eb735cdd981cdd49449595c79"
HEAD_DEFAULT_P106_SOURCE_SHA256 = "2a96044de2455bf5f083090c691fbc693f518e8dbe0cf4d0b265327b90e21586"
HEAD_P116_P106_SOURCE_SHA256 = "1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2"
P80_REQUIRED_MARKERS = (
    "P80_MEDIA_ACTIVE=true",
    "P80_VIDEO_RTP_FORWARDING=PASS",
    "P80_AUDIO_RTP_FORWARDING=PASS",
    "P80_VIDEO_RTP_PACKETS=%llu",
    "P80_AUDIO_RTP_PACKETS=%llu",
)
P116_REQUIRED_MARKERS = (
    "#define P116_RTP_TELEMETRY_CADENCE 50u",
    "#define P116_RTP_TELEMETRY_MAX_PERIODIC_SUMMARIES 12u",
    "p116_observe_rtp(inner, inner_len, payload_type);",
    "p116_print_final_rtp_summary();",
    'printf("P116_%s_COUNT=%llu\\n"',
    'printf("P116_VIDEO_MARKER_COUNT=%llu\\n"',
    'p116_print_summary(&p116_audio_rtp, "AUDIO");',
)

sys.path.insert(0, str(MEDIA))

from entrance_p106_teardown_state_classification_transform import transform


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _generate_with_script(tree: Path, output: Path, *generator_args: str) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tree / "safety-poc" / "research" / "media" / "v1")
    subprocess.run(
        [
            sys.executable,
            str(tree / TRANSFORM_REL),
            "--source",
            str(tree / SOURCE_REL),
            "--output",
            str(output),
            *generator_args,
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return _sha256_bytes(output.read_bytes())


class P116CanonicalGeneratorContractTests(unittest.TestCase):
    def test_historical_p106_archive_still_generates_pinned_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p116-base-") as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "base.tar"
            tree = tmp_path / "tree"
            tree.mkdir()
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(REPO),
                    "archive",
                    HISTORICAL_COMMIT,
                    "-o",
                    str(archive),
                    "safety-poc/research",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            with tarfile.open(archive) as tar:
                tar.extractall(tree, filter="data")

            sha = _generate_with_script(tree, tmp_path / "historical.c")

        self.assertEqual(sha, ARCHIVED_P106_SOURCE_SHA256)

    def test_head_canonical_p106_emits_reachable_p116_and_preserves_p80(self) -> None:
        candidate = transform(
            (REPO / SOURCE_REL).read_text(encoding="utf-8"),
            include_p116=True,
        )
        sha = _sha256_bytes(candidate.encode("utf-8"))

        self.assertEqual(sha, HEAD_P116_P106_SOURCE_SHA256)
        self.assertGreater(candidate.count("P116_"), 0)
        for marker in P116_REQUIRED_MARKERS:
            self.assertIn(marker, candidate)
        for marker in P80_REQUIRED_MARKERS:
            self.assertIn(marker, candidate)
        self.assertLess(
            candidate.index("p116_observe_rtp(inner, inner_len, payload_type);"),
            candidate.index("p80_video_rtp_packets++;"),
        )

    def test_head_canonical_p106_generation_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p116-head-") as tmp:
            tmp_path = Path(tmp)
            run1 = tmp_path / "run1.c"
            run2 = tmp_path / "run2.c"
            sha1 = _generate_with_script(REPO, run1)
            sha2 = _generate_with_script(REPO, run2)

        self.assertEqual(sha1, sha2)
        self.assertEqual(sha1, HEAD_DEFAULT_P106_SOURCE_SHA256)

    def test_head_cli_include_p116_switches_canonical_source_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p116-cli-") as tmp:
            tmp_path = Path(tmp)
            historical = tmp_path / "historical.c"
            explicit_historical = tmp_path / "explicit-historical.c"
            p116 = tmp_path / "p116.c"

            default_sha = _generate_with_script(REPO, historical)
            no_p116_sha = _generate_with_script(REPO, explicit_historical, "--no-include-p116")
            p116_sha = _generate_with_script(REPO, p116, "--include-p116")

        self.assertEqual(default_sha, HEAD_DEFAULT_P106_SOURCE_SHA256)
        self.assertEqual(no_p116_sha, HEAD_DEFAULT_P106_SOURCE_SHA256)
        self.assertEqual(p116_sha, HEAD_P116_P106_SOURCE_SHA256)

    def test_head_digest_pins_are_separate_from_archive_and_fail_on_byte_flip(self) -> None:
        self.assertNotEqual(ARCHIVED_P106_SOURCE_SHA256, HEAD_DEFAULT_P106_SOURCE_SHA256)
        self.assertNotEqual(ARCHIVED_P106_SOURCE_SHA256, HEAD_P116_P106_SOURCE_SHA256)
        source = (REPO / SOURCE_REL).read_text(encoding="utf-8")
        candidate = transform(source, include_p116=True)
        candidate_sha = _sha256_bytes(candidate.encode("utf-8"))
        self.assertEqual(candidate_sha, HEAD_P116_P106_SOURCE_SHA256)

        corrupted = candidate.replace("P116_RTP_TELEMETRY_CADENCE", "P116_RTP_TELEMETRY_CADENCE_CORRUPT", 1)
        corrupted_sha = _sha256_bytes(corrupted.encode("utf-8"))
        self.assertNotEqual(corrupted_sha, HEAD_P116_P106_SOURCE_SHA256)
        with self.assertRaises(AssertionError):
            self.assertEqual(corrupted_sha, HEAD_P116_P106_SOURCE_SHA256)

    def test_canonical_path_uses_p106_entrypoint(self) -> None:
        self.assertTrue((REPO / TRANSFORM_REL).is_file())
        self.assertEqual(
            shutil.which("python3") is not None or shutil.which("python") is not None,
            True,
        )


if __name__ == "__main__":
    unittest.main()
