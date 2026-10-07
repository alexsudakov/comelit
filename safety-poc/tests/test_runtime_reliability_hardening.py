from pathlib import Path
import ast
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class RuntimeReliabilityHardeningTests(unittest.TestCase):
    def test_listener_reader_is_supervised_and_ring_contract_is_nonfatal(self) -> None:
        text = read("custom_components/comelit/runtime.py")
        self.assertIn("native_reader_failed:", text)
        self.assertIn("native_reader_stopped", text)
        self.assertIn("Ignoring malformed Comelit ring observation", text)
        self.assertNotIn("raise ComelitRingRuntimeError(f\\\"ring_contract:{exc}\\\")", text)
        self.assertIn('if line == "V4_RING_OBSERVED=true":', text)
        self.assertIn("self._ring_lines.clear()", text)

    def test_native_children_use_allowlisted_environment(self) -> None:
        for rel in (
            "custom_components/comelit/runtime.py",
            "custom_components/comelit/media_transport.py",
        ):
            text = read(rel)
            self.assertIn("def _native_child_env()", text)
            self.assertNotIn("child_env = os.environ.copy()", text)
            self.assertIn("_SUPPORTED_NATIVE_ARCHITECTURES", text)
            self.assertIn("unsupported_native_architecture", text)

    def test_test_control_webhook_is_not_shipped(self) -> None:
        self.assertFalse((ROOT / "custom_components/comelit/test_control.py").exists())
        init_text = read("custom_components/comelit/__init__.py")
        self.assertNotIn("async_register_test_control", init_text)
        manifest = read("custom_components/comelit/manifest.json")
        self.assertNotIn('"webhook"', manifest)

    def test_unload_does_not_pop_runtime_before_teardown(self) -> None:
        text = read("custom_components/comelit/__init__.py")
        start = text.index("async def async_unload_entry")
        block = text[start:]
        self.assertIn("runtime = runtimes.get(entry.entry_id)", block)
        self.assertNotIn("runtime = runtimes.pop(entry.entry_id, None)", block)
        self.assertLess(block.index("await attempt(\"stop runtime"), block.index("runtimes.pop(entry.entry_id, None)"))

    def test_stream_provider_reuses_and_disposes_single_stream(self) -> None:
        text = read("custom_components/comelit/ring_media.py")
        provider_start = text.index("class HAStreamMediaProvider:")
        close_start = text.index("async def _async_close_unlocked", provider_start)
        record_start = text.index("async def async_record_mp4", close_start)
        close = text[close_start:record_start]
        close_only = close.split("async def async_dispose", 1)[0]
        self.assertIn("self._stream = None", close_only)
        self.assertIn("streams.remove(stream)", close_only)
        self.assertIn("async def async_dispose", close)

    def test_oauth_invalid_grant_starts_reauth_and_backoff_is_bounded(self) -> None:
        oauth = read("custom_components/comelit/oauth.py")
        supervisor = read("custom_components/comelit/supervisor.py")
        flow = read("custom_components/comelit/config_flow.py")
        self.assertIn("ComelitOAuthReauthRequired", oauth)
        self.assertIn('error_obj.get("error") == "invalid_grant"', oauth)
        self.assertIn("async_start_reauth", oauth)
        self.assertIn('last_error == "oauth_reauth_required"', supervisor)
        self.assertIn("RECONNECT_MAX_DELAY_SECONDS = 300", supervisor)
        self.assertIn("async_step_reauth_confirm", flow)

    def test_call_state_timeout_is_bounded_error_not_fake_remote_release(self) -> None:
        runtime = read("custom_components/comelit/runtime.py")
        state = read("custom_components/comelit/call_state.py")
        self.assertIn("_CALL_STATE_TIMEOUT_SECONDS = 120.0", runtime)
        self.assertIn('fail_active("call_state_timeout")', runtime)
        self.assertIn('"call_state_timeout"', state)

    def test_reject_stage_is_validated_before_status_result(self) -> None:
        text = read("custom_components/comelit/runtime.py")
        block = text[text.index('if line.startswith("V4_DOOR_REJECT_STAGE=")'):]
        block = block[:block.index("continue") + len("continue")]
        self.assertIn("_DOOR_LOG_STAGE_RE.fullmatch(reject_stage)", block)

    def test_python_sources_parse(self) -> None:
        for rel in (
            "custom_components/comelit/runtime.py",
            "custom_components/comelit/media_transport.py",
            "custom_components/comelit/supervisor.py",
            "custom_components/comelit/oauth.py",
            "custom_components/comelit/config_flow.py",
            "custom_components/comelit/ring_media.py",
            "custom_components/comelit/__init__.py",
        ):
            ast.parse(read(rel), filename=rel)


if __name__ == "__main__":
    unittest.main()
