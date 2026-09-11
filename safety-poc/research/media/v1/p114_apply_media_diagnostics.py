#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT.parent
TRANSFORM = ROOT / "research" / "media" / "v1" / "entrance_p80_ha_media_runtime_transform.py"
TRANSPORT = REPO / "custom_components" / "comelit" / "media_transport.py"
CAMERA = REPO / "custom_components" / "comelit" / "camera.py"
TEST_TRANSFORM = ROOT / "tests" / "test_p80_ha_media_runtime_transform.py"
TEST_TRANSPORT = ROOT / "tests" / "test_p80_media_transport_static_contract.py"
TEST_CAMERA = ROOT / "tests" / "test_p80_ha_media_entity_wiring.py"


def replace_once_or_applied(text: str, old: str, new: str, label: str) -> str:
    applied_count = text.count(new)
    if applied_count:
        if applied_count != 1:
            raise RuntimeError(
                f"{label}: expected one applied anchor, found {applied_count}"
            )
        if old in text.replace(new, "", 1):
            raise RuntimeError(f"{label}: old anchor remains outside applied anchor")
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one old anchor, found {count}")
    return text.replace(old, new, 1)


def update(path: Path, transforms: list[tuple[str, str, str]], *, write: bool) -> bool:
    original = path.read_text(encoding="utf-8")
    changed = original
    for label, old, new in transforms:
        changed = replace_once_or_applied(changed, old, new, label)
    if write and changed != original:
        path.write_text(changed, encoding="utf-8")
    return changed != original


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    changed: list[str] = []

    if update(
        TRANSFORM,
        [
            (
                "native progress cadence define",
                "#define P80_VIDEO_RTP_PORT {VIDEO_RTP_PORT}\n#define P80_AUDIO_RTP_PORT {AUDIO_RTP_PORT}\n",
                "#define P80_VIDEO_RTP_PORT {VIDEO_RTP_PORT}\n#define P80_AUDIO_RTP_PORT {AUDIO_RTP_PORT}\n#define P80_RTP_PROGRESS_CADENCE 50u\n",
            ),
            (
                "native bounded progress markers",
                '''    if (payload_type == 99u) {{\n        p80_video_rtp_packets++;\n        if (p80_video_rtp_packets == 1u) {{\n            printf("P80_VIDEO_RTP_FORWARDING=PASS\\n");\n            fflush(stdout);\n        }}\n    }} else {{\n        p80_audio_rtp_packets++;\n        if (p80_audio_rtp_packets == 1u) {{\n            printf("P80_AUDIO_RTP_FORWARDING=PASS\\n");\n            fflush(stdout);\n        }}\n    }}\n''',
                '''    if (payload_type == 99u) {{\n        p80_video_rtp_packets++;\n        if (p80_video_rtp_packets == 1u) {{\n            printf("P80_VIDEO_RTP_FORWARDING=PASS\\n");\n            fflush(stdout);\n        }}\n        if (p80_video_rtp_packets == 1u ||\n            p80_video_rtp_packets % P80_RTP_PROGRESS_CADENCE == 0u) {{\n            printf(\n                "P80_VIDEO_RTP_PACKETS=%llu\\n",\n                (unsigned long long)p80_video_rtp_packets\n            );\n            fflush(stdout);\n        }}\n    }} else {{\n        p80_audio_rtp_packets++;\n        if (p80_audio_rtp_packets == 1u) {{\n            printf("P80_AUDIO_RTP_FORWARDING=PASS\\n");\n            fflush(stdout);\n        }}\n        if (p80_audio_rtp_packets == 1u ||\n            p80_audio_rtp_packets % P80_RTP_PROGRESS_CADENCE == 0u) {{\n            printf(\n                "P80_AUDIO_RTP_PACKETS=%llu\\n",\n                (unsigned long long)p80_audio_rtp_packets\n            );\n            fflush(stdout);\n        }}\n    }}\n''',
            ),
            (
                "transform report cadence",
                '            "P80_AUDIO_PAYLOAD_TYPE=8",\n',
                '            "P80_AUDIO_PAYLOAD_TYPE=8",\n            "P80_RTP_PROGRESS_CADENCE=50",\n',
            ),
        ],
        write=args.write,
    ):
        changed.append(str(TRANSFORM.relative_to(REPO)))

    if update(
        TRANSPORT,
        [
            (
                "transport Callable import",
                "import asyncio\nimport hashlib\n",
                "import asyncio\nfrom collections.abc import Callable\nimport hashlib\n",
            ),
            (
                "transport diagnostics import",
                "from .cloud import ComelitCloudError, async_negotiate_p2p\n",
                "from .cloud import ComelitCloudError, async_negotiate_p2p\nfrom .media_diagnostics import MediaProgressDiagnostics\n",
            ),
            (
                "transport notify bound constant",
                "_MEDIA_NATIVE_MARKER_TAIL_LIMIT = 40\n",
                "_MEDIA_NATIVE_MARKER_TAIL_LIMIT = 40\n_MEDIA_STATUS_NOTIFY_MIN_INTERVAL_SECONDS = 1.0\n",
            ),
            (
                "transport diagnostics state",
                "        self._last_native_exit_code: int | None = None\n        self._last_native_failure_markers: list[str] = []\n",
                "        self._last_native_exit_code: int | None = None\n        self._last_native_failure_markers: list[str] = []\n        self._progress = MediaProgressDiagnostics()\n        self._status_listeners: set[Callable[[], None]] = set()\n        self._status_notify_handle: asyncio.TimerHandle | None = None\n        self._last_status_notify_monotonic: float | None = None\n",
            ),
            (
                "transport progress properties",
                '''    @property\n    def audio_forwarding(self) -> bool:\n        return self._audio_forwarding.is_set()\n\n    @property\n    def last_error(self) -> str | None:\n''',
                '''    @property\n    def audio_forwarding(self) -> bool:\n        return self._audio_forwarding.is_set()\n\n    @property\n    def video_packet_count(self) -> int:\n        return self._progress.video_packet_count\n\n    @property\n    def audio_packet_count(self) -> int:\n        return self._progress.audio_packet_count\n\n    @property\n    def last_video_progress_monotonic(self) -> float | None:\n        return self._progress.last_video_progress_monotonic\n\n    @property\n    def last_audio_progress_monotonic(self) -> float | None:\n        return self._progress.last_audio_progress_monotonic\n\n    @property\n    def video_last_packet_age_seconds(self) -> float | None:\n        return self._progress.video_last_packet_age_seconds\n\n    @property\n    def audio_last_packet_age_seconds(self) -> float | None:\n        return self._progress.audio_last_packet_age_seconds\n\n    @property\n    def last_error(self) -> str | None:\n''',
            ),
            (
                "transport bounded status listener",
                '''    @property\n    def last_native_failure_markers(self) -> list[str]:\n        return list(self._last_native_failure_markers)\n\n    def _remember_native_marker(self, line: str) -> None:\n''',
                '''    @property\n    def last_native_failure_markers(self) -> list[str]:\n        return list(self._last_native_failure_markers)\n\n    def async_add_status_listener(self, callback: Callable[[], None]) -> Callable[[], None]:\n        """Register a bounded diagnostics status listener and return its remover."""\n        self._status_listeners.add(callback)\n\n        def remove() -> None:\n            self._status_listeners.discard(callback)\n\n        return remove\n\n    def _cancel_status_notify(self) -> None:\n        handle = self._status_notify_handle\n        if handle is not None:\n            handle.cancel()\n        self._status_notify_handle = None\n\n    def _notify_status_now(self) -> None:\n        self._status_notify_handle = None\n        self._last_status_notify_monotonic = asyncio.get_running_loop().time()\n        for callback in tuple(self._status_listeners):\n            callback()\n\n    def _notify_status_bounded(self) -> None:\n        loop = asyncio.get_running_loop()\n        now = loop.time()\n        last = self._last_status_notify_monotonic\n        if last is None or now - last >= _MEDIA_STATUS_NOTIFY_MIN_INTERVAL_SECONDS:\n            self._cancel_status_notify()\n            self._notify_status_now()\n            return\n        if self._status_notify_handle is None:\n            delay = _MEDIA_STATUS_NOTIFY_MIN_INTERVAL_SECONDS - (now - last)\n            self._status_notify_handle = loop.call_later(delay, self._notify_status_now)\n\n    def _remember_native_marker(self, line: str) -> None:\n''',
            ),
            (
                "transport new-cycle diagnostics reset",
                '''        self._last_native_exit_code = None\n        self._last_native_failure_markers = []\n        self._offer_ready.clear()\n''',
                '''        self._last_native_exit_code = None\n        self._last_native_failure_markers = []\n        self._cancel_status_notify()\n        self._progress.reset()\n        self._last_status_notify_monotonic = None\n        self._offer_ready.clear()\n''',
            ),
            (
                "transport stop notify cancellation",
                '''        self._video_forwarding.clear()\n        self._audio_forwarding.clear()\n        await self._hass.async_add_executor_job(_remove_helper_secret)\n''',
                '''        self._video_forwarding.clear()\n        self._audio_forwarding.clear()\n        self._cancel_status_notify()\n        await self._hass.async_add_executor_job(_remove_helper_secret)\n''',
            ),
            (
                "transport progress marker parser",
                '''            elif line == "P80_AUDIO_RTP_FORWARDING=PASS":\n                self._audio_forwarding.set()\n            elif line in {\n''',
                '''            elif line == "P80_AUDIO_RTP_FORWARDING=PASS":\n                self._audio_forwarding.set()\n            elif line.startswith((\n                "P80_VIDEO_RTP_PACKETS=",\n                "P80_AUDIO_RTP_PACKETS=",\n            )):\n                if self._progress.update_marker(line):\n                    self._notify_status_bounded()\n            elif line in {\n''',
            ),
        ],
        write=args.write,
    ):
        changed.append(str(TRANSPORT.relative_to(REPO)))

    if update(
        CAMERA,
        [
            (
                "camera diagnostics attributes",
                '''    def extra_state_attributes(self) -> dict[str, Any]:\n        status = self._manager.status()\n        return {\n''',
                '''    def extra_state_attributes(self) -> dict[str, Any]:\n        status = self._manager.status()\n        video_age = self._transport.video_last_packet_age_seconds\n        audio_age = self._transport.audio_last_packet_age_seconds\n        return {\n''',
            ),
            (
                "camera diagnostics payload",
                '''            "video_forwarding": self._transport.video_forwarding,\n            "audio_forwarding": self._transport.audio_forwarding,\n            "automatic_session_start": False,\n''',
                '''            "video_forwarding": self._transport.video_forwarding,\n            "audio_forwarding": self._transport.audio_forwarding,\n            "video_packet_count": self._transport.video_packet_count,\n            "audio_packet_count": self._transport.audio_packet_count,\n            "video_last_packet_age_seconds": (\n                round(video_age, 1) if video_age is not None else None\n            ),\n            "audio_last_packet_age_seconds": (\n                round(audio_age, 1) if audio_age is not None else None\n            ),\n            "automatic_session_start": False,\n''',
            ),
            (
                "camera transport status listener",
                '''        self.async_on_remove(\n            self._manager.async_add_status_listener(self._handle_status_update)\n        )\n\n    async def async_will_remove_from_hass(self) -> None:\n''',
                '''        self.async_on_remove(\n            self._manager.async_add_status_listener(self._handle_status_update)\n        )\n        self.async_on_remove(\n            self._transport.async_add_status_listener(self._handle_status_update)\n        )\n\n    async def async_will_remove_from_hass(self) -> None:\n''',
            ),
        ],
        write=args.write,
    ):
        changed.append(str(CAMERA.relative_to(REPO)))

    if update(
        TEST_TRANSFORM,
        [
            (
                "transform test bounded diagnostics",
                '''        self.assertIn("P80_AUDIO_RTP_FORWARDING=PASS", self.candidate)\n\n    def test_wrapper_profile_is_frozen_per_media_payload_type(self) -> None:\n''',
                '''        self.assertIn("P80_AUDIO_RTP_FORWARDING=PASS", self.candidate)\n\n    def test_rtp_progress_markers_are_numeric_and_bounded(self) -> None:\n        self.assertIn("#define P80_RTP_PROGRESS_CADENCE 50u", self.candidate)\n        self.assertIn("P80_VIDEO_RTP_PACKETS=%", self.candidate)\n        self.assertIn("P80_AUDIO_RTP_PACKETS=%", self.candidate)\n        self.assertIn("p80_video_rtp_packets % P80_RTP_PROGRESS_CADENCE == 0u", self.candidate)\n        self.assertIn("p80_audio_rtp_packets % P80_RTP_PROGRESS_CADENCE == 0u", self.candidate)\n        self.assertNotIn("P80_VIDEO_RTP_PACKETS=%s", self.candidate)\n        self.assertNotIn("P80_AUDIO_RTP_PACKETS=%s", self.candidate)\n\n    def test_wrapper_profile_is_frozen_per_media_payload_type(self) -> None:\n''',
            ),
        ],
        write=args.write,
    ):
        changed.append(str(TEST_TRANSFORM.relative_to(REPO)))

    if update(
        TEST_TRANSPORT,
        [
            (
                "transport diagnostics static contract",
                '''    def test_native_failure_diagnostics_are_allowlisted_redacted_and_bounded(self) -> None:\n''',
                '''    def test_progress_diagnostics_are_monotonic_bounded_and_entity_notified(self) -> None:\n        self.assertIn("MediaProgressDiagnostics", self.source)\n        self.assertIn("_MEDIA_STATUS_NOTIFY_MIN_INTERVAL_SECONDS = 1.0", self.source)\n        self.assertIn("video_packet_count", self.source)\n        self.assertIn("audio_packet_count", self.source)\n        self.assertIn("video_last_packet_age_seconds", self.source)\n        self.assertIn("audio_last_packet_age_seconds", self.source)\n        self.assertIn('"P80_VIDEO_RTP_PACKETS="', self.source)\n        self.assertIn('"P80_AUDIO_RTP_PACKETS="', self.source)\n        self.assertIn("self._progress.update_marker(line)", self.source)\n        self.assertIn("loop.call_later(delay, self._notify_status_now)", self.source)\n        self.assertIn("self._progress.reset()", self.source)\n        self.assertIn("self._cancel_status_notify()", self.source)\n\n    def test_native_failure_diagnostics_are_allowlisted_redacted_and_bounded(self) -> None:\n''',
            ),
        ],
        write=args.write,
    ):
        changed.append(str(TEST_TRANSPORT.relative_to(REPO)))

    if update(
        TEST_CAMERA,
        [
            (
                "camera diagnostics entity test",
                '''    def test_stream_dependency_is_explicit(self) -> None:\n''',
                '''    def test_camera_exposes_bounded_runtime_progress_diagnostics(self) -> None:\n        self.assertIn('"video_packet_count": self._transport.video_packet_count', self.camera)\n        self.assertIn('"audio_packet_count": self._transport.audio_packet_count', self.camera)\n        self.assertIn('"video_last_packet_age_seconds":', self.camera)\n        self.assertIn('"audio_last_packet_age_seconds":', self.camera)\n        self.assertIn("self._transport.async_add_status_listener", self.camera)\n        self.assertNotIn("should_poll = True", self.camera)\n\n    def test_stream_dependency_is_explicit(self) -> None:\n''',
            ),
        ],
        write=args.write,
    ):
        changed.append(str(TEST_CAMERA.relative_to(REPO)))

    print("=== COMELIT P114 APPLY DIAGNOSTICS ===")
    print(f"MODE={'WRITE' if args.write else 'CHECK'}")
    print(f"CHANGED_COUNT={len(changed)}")
    for path in changed:
        print(f"CHANGED={path}")
    print("RESULT=PASS")
    print("=== END COMELIT P114 APPLY DIAGNOSTICS ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
