from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

class WebCodecsSourceTerminalEvidenceTests(unittest.TestCase):
    def test_source_terminal_reason_is_bounded_and_classified(self) -> None:
        text = (ROOT / "custom_components/comelit/miniapp/webcodecs.py").read_text(encoding="utf-8")
        self.assertIn("COMELIT_MINIAPP_WEBCODECS_SOURCE_TERMINAL", text)
        self.assertIn("terminal_cause=source_eof", text)
        self.assertIn("terminal_cause=source_transport_closed:%s", text)
        self.assertIn("type(exc).__name__", text)

    def test_raw_exception_text_is_not_logged(self) -> None:
        text = (ROOT / "custom_components/comelit/miniapp/webcodecs.py").read_text(encoding="utf-8")
        start = text.index("packet = next(iterator, None)")
        end = text.index("future.set_exception(exc)", start) + len("future.set_exception(exc)")
        block = text[start:end]
        self.assertNotIn("str(exc)", block)
        self.assertNotIn("repr(exc)", block)

if __name__ == "__main__":
    unittest.main()
