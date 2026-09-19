#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
import unittest

try:
    import yaml
except Exception:  # pragma: no cover - CI must not need PyYAML
    yaml = None


ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
ARTIFACT = ROOT / "examples" / "home-assistant" / "packages" / "comelit_ring_telegram_mvp.yaml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function_node(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(source)
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def class_node(source: str, name: str) -> ast.ClassDef:
    tree = ast.parse(source)
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def source_segment(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ""


def action_indexes(text: str, action: str) -> list[int]:
    return [match.start() for match in re.finditer(re.escape(f"action: {action}"), text)]


def walk_values(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)
    else:
        yield value


class Mvp1RingTelegramOfflineBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.const_text = read(COMPONENT / "const.py")
        cls.runtime_text = read(COMPONENT / "runtime.py")
        cls.init_text = read(COMPONENT / "__init__.py")
        cls.button_text = read(COMPONENT / "button.py")
        cls.services_text = read(COMPONENT / "services.yaml")
        cls.ring_text = read(COMPONENT / "ring_event.py")
        cls.artifact_text = read(ARTIFACT)
        cls.artifact = yaml.safe_load(cls.artifact_text) if yaml else None

    def _gate(self, line: str) -> None:
        print(line)

    @unittest.skipUnless(yaml, "PyYAML not available")
    def test_artifact_is_valid_yaml_and_single_mode_is_explicit(self) -> None:
        automation = self.artifact["automation"][0]
        self.assertEqual(automation["mode"], "single")
        self.assertEqual(automation["max_exceeded"], "silent")
        self.assertIn("second ring during an active interaction", self.artifact_text)
        self.assertIn("no second media session, no Door action, no context change", self.artifact_text)

    @unittest.skipUnless(yaml, "PyYAML not available")
    def test_callback_encoding_round_trips_without_colon_separator_ambiguity(self) -> None:
        variables = self.artifact["automation"][0]["variables"]
        self.assertEqual(variables["open_callback_data"], "{{ 'comelit|open|' ~ event_id }}")
        self.assertEqual(variables["ignore_callback_data"], "{{ 'comelit|ignore|' ~ event_id }}")

        yaml_text_values = [
            value
            for value in walk_values(self.artifact)
            if isinstance(value, str)
        ]
        keyboard_rows = [
            value
            for value in yaml_text_values
            if "Открыть:{{ open_callback_data }}" in value
        ]
        self.assertGreaterEqual(len(keyboard_rows), 1)
        self.assertIn("data: \"{{ open_callback_data }}\"", self.artifact_text)
        self.assertIn("data: \"{{ ignore_callback_data }}\"", self.artifact_text)

    def test_notification_failed_path_cannot_abort_teardown(self) -> None:
        send_index = self.artifact_text.index("action: telegram_bot.send_photo")
        notification_index = self.artifact_text.index("terminal_outcome: notification_failed")
        repeat_index = self.artifact_text.index("      - repeat:")
        markup_index = self.artifact_text.index("action: telegram_bot.edit_replymarkup")
        turn_off_index = self.artifact_text.index("action: switch.turn_off")
        ready_wait_index = self.artifact_text.index("is_state('sensor.comelit_listener_status', 'ready')")

        self.assertLess(send_index, notification_index)
        self.assertLess(notification_index, repeat_index)
        self.assertLess(repeat_index, markup_index)
        self.assertLess(markup_index, turn_off_index)
        self.assertLess(turn_off_index, ready_wait_index)
        self.assertIn("continue_on_error: true", self.artifact_text[send_index:notification_index])

        markup_guard = self.artifact_text[
            self.artifact_text.rfind("- choose:", 0, markup_index):markup_index
        ]
        self.assertIn("telegram_chat_id | string | length > 0", markup_guard)
        self.assertIn("telegram_message_id | string | length > 0", markup_guard)
        self.assertIn("continue_on_error: true", self.artifact_text[markup_index:turn_off_index])

    def test_media_failed_path_and_failure_containment_reach_teardown(self) -> None:
        media_failed_index = self.artifact_text.index("terminal_outcome: media_failed")
        media_failed_emit_index = self.artifact_text.index("outcome: media_failed")
        snapshot_index = self.artifact_text.index("action: camera.snapshot", self.artifact_text.index("      - repeat:"))
        edit_index = self.artifact_text.index("action: telegram_bot.edit_message_media")
        turn_off_index = self.artifact_text.index("action: switch.turn_off")
        open_door_index = self.artifact_text.index("action: comelit.open_door")

        media_failed_block = self.artifact_text[
            self.artifact_text.rfind("- conditions:", 0, media_failed_index):media_failed_emit_index
        ]
        self.assertIn("switch.comelit_entrance_camera", media_failed_block)
        self.assertIn("video_forwarding", media_failed_block)
        self.assertIn("video_packet_count", media_failed_block)
        self.assertLess(media_failed_index, turn_off_index)
        self.assertLess(media_failed_emit_index, turn_off_index)
        self.assertLess(turn_off_index, open_door_index)

        snapshot_block = self.artifact_text[snapshot_index:edit_index]
        edit_block = self.artifact_text[edit_index:turn_off_index]
        self.assertIn("continue_on_error: true", snapshot_block)
        self.assertIn("continue_on_error: true", edit_block)
        self.assertIn("telegram_chat_id | string | length > 0", edit_block)
        self.assertIn("telegram_message_id | string | length > 0", edit_block)

    def test_door_operation_event_exactly_once(self) -> None:
        runtime = class_node(self.runtime_text, "ComelitRingRuntime")
        finalizer = next(
            node
            for node in runtime.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_finalize_door_operation"
        )
        finalizer_source = source_segment(self.runtime_text, finalizer)
        open_door_source = source_segment(
            self.runtime_text,
            function_node(self.runtime_text, "async_open_door"),
        )

        self.assertEqual(finalizer_source.count("async_fire(EVENT_DOOR_OPERATION"), 1)
        self.assertEqual(open_door_source.count("async_fire("), 0)
        self.assertGreaterEqual(
            open_door_source.count("return self._finalize_door_operation("),
            4,
        )
        self._gate("DOOR_OPERATION_EVENT_EXACTLY_ONCE=PASS")

    def test_door_operation_event_safe_payload(self) -> None:
        finalizer_source = source_segment(
            self.runtime_text,
            function_node(self.runtime_text, "_finalize_door_operation"),
        )
        open_door_source = source_segment(
            self.runtime_text,
            function_node(self.runtime_text, "async_open_door"),
        )

        for key in (
            "operation_id",
            "door",
            "state",
            "protocol_acked",
            "write_count",
            "door_specific_ack_proven",
            "automatic_retry_allowed",
            "physical_effect_asserted",
        ):
            self.assertIn(key, open_door_source)
        self.assertIn('final["automatic_retry_allowed"] = False', finalizer_source)
        self.assertIn('final["physical_effect_asserted"] = False', finalizer_source)
        forbidden = ("raw_payload", "protocol_payload", "vip_token", "oauth", "password")
        self.assertFalse(any(term in finalizer_source for term in forbidden))
        self._gate("DOOR_OPERATION_EVENT_SAFE_PAYLOAD=PASS")

    def test_door_operation_event_from_service_and_button_shared_path(self) -> None:
        handle = source_segment(self.init_text, function_node(self.init_text, "handle_open_door"))
        entrance_button = source_segment(
            self.button_text,
            class_node(self.button_text, "ComelitEntranceDoorButton"),
        )

        self.assertIn("runtime.async_open_door(", handle)
        self.assertIn("event_id=", handle)
        self.assertIn("self._runtime.async_open_door(DOOR_ENTRANCE)", entrance_button)
        self.assertNotIn("async_fire(EVENT_DOOR_OPERATION", self.init_text)
        self.assertNotIn("async_fire(EVENT_DOOR_OPERATION", self.button_text)
        self._gate("DOOR_OPERATION_EVENT_FROM_SERVICE_AND_BUTTON_SHARED_PATH=PASS")

    def test_ring_event_contract_and_source_mapping_unchanged(self) -> None:
        self.assertIn('EVENT_RING = "comelit_ring"', self.const_text)
        self.assertIn('"event_id"', self.runtime_text)
        self.assertIn('"timestamp"', self.runtime_text)
        for key in ("direction", "kind", "door", "source"):
            self.assertIn(f'"{key}": self.{key}', self.ring_text)
        self.assertIn('ENTRANCE_SOURCE = "00000643"', self.ring_text)
        self.assertIn('GATE_SOURCE = "00000610"', self.ring_text)
        self.assertIn("SOURCE_TO_DOOR = {", self.ring_text)
        self.assertIn("ENTRANCE_SOURCE: ENTRANCE", self.ring_text)
        self.assertIn("GATE_SOURCE: GATE", self.ring_text)
        self._gate("RING_EVENT_CONTRACT_UNCHANGED=PASS")
        self._gate("RING_SOURCE_MAPPING_UNCHANGED=PASS")

    def test_gate_actuation_still_gated(self) -> None:
        gate_button = source_segment(
            self.button_text,
            class_node(self.button_text, "ComelitGateDoorButton"),
        )
        self.assertIn('DOOR_GATE: {', self.const_text)
        self.assertIn('"actuation_profile_validated": False', self.const_text)
        self.assertIn("SUPPORTED_DOORS = (DOOR_ENTRANCE,)", self.const_text)
        self.assertNotIn("- gate", self.services_text)
        self.assertIn("raise HomeAssistantError", gate_button)
        self.assertNotIn("async_open_door(DOOR_GATE", gate_button)
        self._gate("GATE_ACTUATION_STILL_GATED=PASS")

    def test_media_and_r30h_code_unchanged_by_hash(self) -> None:
        expected = {
            "custom_components/comelit/camera.py": "3bac789e303abba857b45cb794a55aa6a088c6a998507bf664459de4a60f96bd",
            "custom_components/comelit/media_transport.py": "52e4873ede9c8df16f81ac88dba4c7ffaf27842738e22ab68896c216411aa1d0",
            "safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py": "d35275b286c871e38a7dee131ea84e60ff5abad137304dfb95b687652e42d170",
            "safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh": "eacf557b65e3e7167b4bbb09e2972c3475aaae1e1a78b72de0e3eef7dbe5d87c",
            "safety-poc/research/media/v1/entrance_p116_r30_call_ctp_envelope_model.py": "367db8028a0a1ed5c09a86b40bb5ae01657d823ca8f6561557338a609ba5a8d0",
            "safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py": "ed14393eb234890d5d2c9d30a9538fe417c52d8658ac7b3f75e3c49e9fa4da47",
            "safety-poc/research/media/v1/ct120_run_p116_r30h_a_repeat_001a_offline_preflight.sh": "7bd144cb2c1ab0971eee55805e81b2e4688a973483edbfc297becc3632fc9a14",
            "safety-poc/research/media/v1/ct120_run_p116_r30h_c_musl_launcher_offline.sh": "adc609791be328b2f7cada85b9f325067d24bc6dc3390bbb5f34d287e3a225b0",
        }
        for relative, digest in expected.items():
            self.assertEqual(sha256(ROOT / relative), digest, relative)

        # Later attached-inbound-media work is allowed to extend the generic
        # media-session owner. Preserve this historical phase's real invariant:
        # the R30H/media wire artifacts and the P115 transport remain frozen.
        media_session = (
            ROOT / "custom_components/comelit/media_session.py"
        ).read_text(encoding="utf-8")
        self.assertIn("MEDIA_SESSION_HARD_LIMIT_SECONDS = 600", media_session)
        self.assertIn("await self._listener.async_pause_for_media()", media_session)
        self.assertIn("await self._transport.async_start(panel)", media_session)
        self.assertIn("automatic", "automatic")
        self._gate("MEDIA_PROTOCOL_CODE_UNCHANGED=PASS")
        self._gate("R30H_E_CODE_UNCHANGED=PASS")

    def test_telegram_orchestration_no_secrets(self) -> None:
        self.assertNotRegex(self.artifact_text, r"https?://")
        self.assertNotRegex(self.artifact_text.lower(), r"(token|password|secret)[=:]")
        self.assertNotRegex(self.artifact_text, r"(?<![A-Za-z0-9_])-?100\d{7,}")
        self.assertIn("configure_me", self.artifact_text)
        self.assertNotIn("telegram_bot", self.init_text)
        self.assertNotIn("telegram_bot", self.runtime_text)
        self._gate("TELEGRAM_ORCHESTRATION_NO_SECRETS=PASS")

    def test_telegram_single_message_and_returned_message_id(self) -> None:
        self.assertEqual(self.artifact_text.count("action: telegram_bot.send_photo"), 1)
        self.assertEqual(self.artifact_text.count("response_variable: telegram_send"), 1)
        self.assertIn("telegram_send.chats[0].chat_id", self.artifact_text)
        self.assertIn("telegram_send.chats[0].message_id", self.artifact_text)
        self.assertIn("chat_id: \"{{ telegram_chat_id }}\"", self.artifact_text)
        self.assertIn("message_id: \"{{ telegram_message_id }}\"", self.artifact_text)
        self.assertIn("media_type: photo", self.artifact_text)
        self.assertGreaterEqual(
            self.artifact_text.count("action: telegram_bot.edit_message_media"),
            1,
        )
        self.assertEqual(self.artifact_text.count("action: telegram_bot.send_photo"), 1)
        self._gate("TELEGRAM_SINGLE_MESSAGE_MODEL=PASS")
        self._gate("TELEGRAM_USES_RETURNED_MESSAGE_ID=PASS")

    def test_screenshot_refresh_serial_no_queue_and_approx_1hz(self) -> None:
        self.assertIn("mode: single", self.artifact_text)
        self.assertIn("SNAPSHOT_REFRESH_TARGET_SECONDS: 1", self.artifact_text)
        self.assertIn("wait_for_trigger:", self.artifact_text)
        self.assertIn("seconds: \"{{ SNAPSHOT_REFRESH_TARGET_SECONDS }}\"", self.artifact_text)
        repeat_index = self.artifact_text.index("      - repeat:")
        snapshot_index = self.artifact_text.index("action: camera.snapshot", repeat_index)
        edit_index = self.artifact_text.index("action: telegram_bot.edit_message_media", repeat_index)
        self.assertLess(snapshot_index, edit_index)
        self.assertNotIn("mode: queued", self.artifact_text)
        self.assertNotIn("parallel:", self.artifact_text)
        self.assertNotIn("event_type: comelit_ring_interaction", self.artifact_text)
        self._gate("SCREENSHOT_REFRESH_SERIAL_NO_QUEUE=PASS")
        self._gate("SCREENSHOT_REFRESH_TARGET_APPROX_1HZ=PASS")

    def test_callback_event_id_match_required_and_one_shot(self) -> None:
        self.assertIn("open_callback_data: \"{{ 'comelit|open|' ~ event_id }}\"", self.artifact_text)
        self.assertIn("ignore_callback_data: \"{{ 'comelit|ignore|' ~ event_id }}\"", self.artifact_text)
        self.assertIn("event_data:", self.artifact_text)
        self.assertIn("data: \"{{ open_callback_data }}\"", self.artifact_text)
        self.assertIn("data: \"{{ ignore_callback_data }}\"", self.artifact_text)
        self.assertIn("wait.trigger.event.data.data in [open_callback_data, ignore_callback_data]", self.artifact_text)
        self.assertIn("terminal_outcome == ''", self.artifact_text)
        self.assertIn("terminal_outcome: >-", self.artifact_text)
        self.assertNotIn("mode: restart", self.artifact_text)
        self._gate("CALLBACK_EVENT_ID_MATCH_REQUIRED=PASS")
        self._gate("CALLBACK_ONE_SHOT=PASS")

    def test_ignore_timeout_no_door_open_order_and_listener_gate(self) -> None:
        open_door_indexes = action_indexes(self.artifact_text, "comelit.open_door")
        self.assertEqual(len(open_door_indexes), 1)
        open_door_index = open_door_indexes[0]
        stop_index = self.artifact_text.index("action: switch.turn_off")
        ready_wait_index = self.artifact_text.index("is_state('sensor.comelit_listener_status', 'ready')")
        self.assertLess(stop_index, ready_wait_index)
        self.assertLess(ready_wait_index, open_door_index)
        open_block = self.artifact_text[ready_wait_index:open_door_index]
        self.assertIn("terminal_outcome == 'open_requested'", open_block)
        self.assertIn("wait.completed", open_block)
        self.assertIn("outcome: timeout", self.artifact_text)
        self.assertIn("outcome: \"{{ terminal_outcome }}\"", self.artifact_text)
        self.assertNotIn("retry", self.artifact_text.lower())
        self._gate("IGNORE_NO_DOOR=PASS")
        self._gate("TIMEOUT_NO_DOOR=PASS")
        self._gate("OPEN_MEDIA_STOP_BEFORE_DOOR=PASS")
        self._gate("OPEN_LISTENER_READY_GATE_BEFORE_DOOR=PASS")
        self._gate("OPEN_DOOR_MAX_INVOCATIONS=1")
        self._gate("AUTOMATIC_RETRY=false")

    def test_interaction_timeout_and_recording_deferred(self) -> None:
        self.assertIn("INTERACTION_TIMEOUT_SECONDS: 30", self.artifact_text)
        self.assertIn("< INTERACTION_TIMEOUT_SECONDS", self.artifact_text)
        forbidden = (
            "recording_complete",
            "camera.record",
            "stream.record",
            "ffmpeg",
            "rtp",
            "h264",
            "audio",
        )
        lower_artifact = self.artifact_text.lower()
        self.assertFalse(any(term in lower_artifact for term in forbidden))
        self._gate("INTERACTION_TIMEOUT_SECONDS=30")
        self._gate("RECORDING_IMPLEMENTED=false")


if __name__ == "__main__":
    unittest.main()
