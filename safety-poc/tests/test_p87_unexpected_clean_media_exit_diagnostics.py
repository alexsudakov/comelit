from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
TRANSPORT = ROOT / "custom_components" / "comelit" / "media_transport.py"


class P87UnexpectedCleanMediaExitDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TRANSPORT.read_text(encoding="utf-8")

    def test_post_active_exit_is_failure_even_when_returncode_is_zero(self) -> None:
        self.assertNotIn("if rc != 0 and not self._stopping:", self.source)
        self.assertIn(
            "if not self._stopping:\n"
            "                self._capture_native_failure(rc)\n"
            "                raise ComelitMediaTransportError(f\"media_native_exit:{rc}\")",
            self.source,
        )

    def test_planned_stop_marks_transport_stopping(self) -> None:
        async_stop = self.source.index("    async def async_stop(self) -> None:")
        run_once = self.source.index("    async def _async_run_once(self) -> None:", async_stop)
        stop_block = self.source[async_stop:run_once]
        self.assertIn("self._stopping = True", stop_block)

    def test_native_marker_tail_is_captured_before_unexpected_exit_error(self) -> None:
        capture = self.source.index("self._capture_native_failure(rc)")
        error = self.source.index(
            'raise ComelitMediaTransportError(f"media_native_exit:{rc}")', capture
        )
        self.assertLess(capture, error)


if __name__ == "__main__":
    unittest.main()
