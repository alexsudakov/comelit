from contextlib import redirect_stdout
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
LAUNCHER = MEDIA_DIR / "ct120_launch_entrance_post_ack_structural_probe_v1.sh"
BASE_LAUNCHER = MEDIA_DIR / "ct120_launch_entrance_device_video_ack_observation_probe_v1.sh"
CLASSIFIER = MEDIA_DIR / "entrance_post_ack_structural_classifier_transform.py"


def git_blob_sha(text: str) -> str:
    data = text.encode("utf-8")
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


class P49EntrancePostAckStructuralLauncherContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")
        cls.base_launcher = BASE_LAUNCHER.read_text(encoding="utf-8")
        cls.classifier = CLASSIFIER.read_text(encoding="utf-8")

        prefix = 'python3 - "$BASE_LAUNCHER" "$PATCHED_LAUNCHER" > "$PATCH_LOG" 2>&1 <<\'PY\'\n'
        suffix = "\nPY\nPATCH_RC=$?"
        start = cls.launcher.index(prefix) + len(prefix)
        end = cls.launcher.index(suffix, start)
        cls.patch_python = cls.launcher[start:end]

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "base-launcher.sh"
            output = Path(tmp) / "patched-launcher.sh"
            source.write_text(cls.base_launcher, encoding="utf-8")

            old_argv = sys.argv
            capture = io.StringIO()
            try:
                sys.argv = ["launcher-patch", str(source), str(output)]
                with redirect_stdout(capture):
                    exec(
                        compile(cls.patch_python, "<p49-launcher-patch>", "exec"),
                        {"__name__": "__main__"},
                    )
            finally:
                sys.argv = old_argv

            cls.patch_output = capture.getvalue()
            cls.patched_launcher = output.read_text(encoding="utf-8")

    def test_exact_base_launcher_and_classifier_blob_pins_match_repository_bytes(self):
        self.assertEqual(
            git_blob_sha(self.base_launcher),
            "093007b8930b19c069d253df19391d72e739122c",
        )
        self.assertEqual(
            git_blob_sha(self.classifier),
            "269ad1b22d318551966b4f1a927c755f9ed00156",
        )
        self.assertIn(
            "BASE_LAUNCHER_EXPECTED_BLOB=093007b8930b19c069d253df19391d72e739122c",
            self.launcher,
        )
        self.assertIn(
            "CLASSIFIER_TRANSFORM_EXPECTED_BLOB=269ad1b22d318551966b4f1a927c755f9ed00156",
            self.launcher,
        )
        self.assertIn("PROVENANCE_GATE=PASS", self.launcher)

    def test_real_patch_changes_only_transform_selection_and_marker(self):
        self.assertIn("P47_LAUNCHER_PATCH_GATE=PASS", self.patch_output)
        self.assertIn(
            "P47_RUNNER_TRANSFORM=entrance_post_ack_structural_classifier_transform.py",
            self.patch_output,
        )
        self.assertIn("P47_NETWORK_SEQUENCE_CHANGED=false", self.patch_output)
        self.assertIn("P47_AUTOMATIC_RETRY=false", self.patch_output)

        old_transform = '''new_transform = (
    "TRANSFORM_REL=safety-poc/research/media/v1/"
    "entrance_device_video_ack_observation_transform.py"
)
'''
        new_transform = '''new_transform = (
    "TRANSFORM_REL=safety-poc/research/media/v1/"
    "entrance_post_ack_structural_classifier_transform.py"
)
'''
        old_marker = 'print("RUNNER_TRANSFORM=entrance_device_video_ack_observation_transform.py")'
        new_marker = 'print("RUNNER_TRANSFORM=entrance_post_ack_structural_classifier_transform.py")'

        expected = self.base_launcher.replace(old_transform, new_transform, 1)
        expected = expected.replace(old_marker, new_marker, 1)
        self.assertEqual(self.patched_launcher, expected)

    def test_patched_p47_retains_reviewed_one_shot_network_and_listener_boundary(self):
        for marker in (
            "BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a",
            "ACK_OBS_TRANSFORM_EXPECTED_BLOB=5a87e2531c2cef0297d8a7e84d75f9d4f2182311",
            "OBS_TRANSFORM_EXPECTED_BLOB=85a66b95d4f2ed633f978901fc9041d4a5999531",
            "SIGNAL_TRANSFORM_EXPECTED_BLOB=b8cdb7fc70b3475ad5b6a0cb0077ef0430f95f30",
            "PRESTART_TRANSFORM_EXPECTED_BLOB=7b1b79706abb9c2273bfa42c83760fade7b823c8",
            "RUNNER_FINAL_DEVICE_VIDEO_ACK_ALLOWED=true",
            "RUNNER_AUTOMATIC_RETRY=false",
        ):
            self.assertIn(marker, self.patched_launcher)

        # P47 stores runner transform paths inside its embedded Python patch as
        # adjacent string literals. The previous test proves byte-for-byte that
        # only the reviewed new_transform and informational marker changed.
        self.assertIn(
            '"entrance_post_ack_structural_classifier_transform.py"',
            self.patched_launcher,
        )
        runner_invocation = '"$PATCHED_RUNNER" > "$DETAIL_LOG" 2>&1'
        self.assertEqual(self.patched_launcher.count(runner_invocation), 1)
        self.assertNotIn("for attempt in", self.patched_launcher)
        self.assertNotIn("while true", self.patched_launcher)

    def test_wrapper_invokes_patched_p47_exactly_once_and_has_no_retry(self):
        invocation = '"$PATCHED_LAUNCHER" > "$BASE_OUTPUT" 2>&1'
        self.assertEqual(self.launcher.count(invocation), 1)
        self.assertNotIn("for attempt in", self.launcher)
        self.assertNotIn("while true", self.launcher)
        self.assertIn("Exactly one P47 launcher invocation", self.launcher)

    def test_outer_gate_requires_structural_integrity_and_base_live_pass(self):
        for marker in (
            '[ "$base_result" = PASS ]',
            '[ "$live_invocations" = 1 ]',
            '[ "$ack_sent" = 1 ]',
            '[ "$final_ack" = true ]',
            '[ "$obs_result" = 1 ]',
            '[ "$listener_after" = PASS ]',
            '[ "$auto_retry" = false ]',
            '[ "$payload_stored" = false ]',
            '[ "$payload_emitted" = false ]',
            '[ "$rtp_inspection" = false ]',
            '[ "$door_action" = false ]',
            '[ "$media_capture" = false ]',
            '[ "$struct_malformed" -eq 0 ]',
            '[ "$struct_lines" -eq "$struct_frames" ]',
            '[ $((struct_ctpp + struct_other)) -eq "$struct_frames" ]',
            '[ "$struct_tail" -le 511 ]',
            '[ "$struct_raw" = false ]',
            '[ "$struct_hex" = false ]',
            '[ "$struct_base64" = false ]',
            "CT120_ENTRANCE_POST_ACK_STRUCTURAL_LAUNCH=PASS",
        ):
            self.assertIn(marker, self.launcher)

    def test_summary_exposes_structural_metadata_but_no_payload_content(self):
        for marker in (
            "STRUCT_FRAME_LINES=$struct_lines",
            "STRUCT_FRAMES=$struct_frames",
            "STRUCT_CTPP_FRAMES=$struct_ctpp",
            "STRUCT_OTHER_FRAMES=$struct_other",
            "STRUCT_MALFORMED=$struct_malformed",
            "STRUCT_TAIL_BYTES=$struct_tail",
            "STRUCT_RAW_PAYLOAD_EMITTED=$struct_raw",
            "STRUCT_HEX_EMITTED=$struct_hex",
            "STRUCT_BASE64_EMITTED=$struct_base64",
            "ENTRANCE_POST_ACK_STRUCT_FRAME=",
            "AUTOMATIC_RETRY=$auto_retry",
        ):
            self.assertIn(marker, self.launcher)

        for forbidden in (
            "PAYLOAD_HEX",
            "PAYLOAD_BASE64",
            "base64.b64encode",
            "tcpdump",
            "tshark",
            "xxd",
        ):
            self.assertNotIn(forbidden, self.launcher)

    def test_classifier_dependency_keeps_single_ack_and_no_media_decode(self):
        for marker in (
            'print("ENTRANCE_DEVICE_VIDEO_ACK_MAX_SENDS=1")',
            'print("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true")',
            'print("ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=3000")',
            'print("ENTRANCE_POST_ACK_STRUCT_RAW_PAYLOAD_EMITTED=false")',
            'print("ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false")',
            'print("DOOR_ACTION_SENT=false")',
            'print("NETWORK_IO_PERFORMED=false")',
        ):
            self.assertIn(marker, self.classifier)


if __name__ == "__main__":
    unittest.main()
