from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class AttachedRtpObservabilityContractTests(unittest.TestCase):
    def test_h264_shim_exposes_bounded_input_timing(self) -> None:
        text = (ROOT / "custom_components/comelit/h264_recovery.py").read_text(encoding="utf-8")
        self.assertIn("def input_rtp_diagnostics", text)
        self.assertIn('"first_rtp_at": self._first_rtp_at', text)
        self.assertIn('"last_rtp_at": self._last_rtp_at', text)
        self.assertIn('"last_rtp_age_ms": age_ms', text)

    def test_attached_transport_retains_last_stopped_session(self) -> None:
        text = (ROOT / "custom_components/comelit/attached_media.py").read_text(encoding="utf-8")
        self.assertIn("self._last_video_observability", text)
        self.assertIn('"attached_video_input_packets"', text)
        self.assertIn('"attached_video_last_rtp_at"', text)
        self.assertIn('"attached_video_last_rtp_age_ms"', text)
        capture = text.index("timing = shim.input_rtp_diagnostics()")
        clear = text.index("self._video_recovery_shim = None", capture)
        self.assertLess(capture, clear)

    def test_camera_publishes_attached_observability(self) -> None:
        text = (ROOT / "custom_components/comelit/camera.py").read_text(encoding="utf-8")
        self.assertIn("self._attached_transport.video_observability_diagnostics()", text)


if __name__ == "__main__":
    unittest.main()
