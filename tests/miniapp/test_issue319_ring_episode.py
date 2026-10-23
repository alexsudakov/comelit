from __future__ import annotations

import asyncio
import json
from pathlib import Path
import importlib.util
import sys
import types
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import _load_component_module, load_plain_module


ring_episode = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_episode.py", "ring_episode"
)
ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow_episode_containment"
)
media_diagnostics = load_plain_module(
    str(ROOT),
    "custom_components/comelit/media_diagnostics.py",
    "ring_episode_media_diagnostics",
)

MEDIA = ring_shadow.SHADOW_OWNER_MEDIA


class Clock:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        return self.value


def _ledger(**kwargs):
    clock = kwargs.pop("clock", None) or Clock()
    return ring_episode.RingEpisodeLedger(clock=clock, **kwargs), clock


def _load_sensor_module(supervisor_module):
    """Load the real sensor entity with only HA framework types stubbed."""
    package_name = supervisor_module.__package__
    module_names = (
        "homeassistant.components.sensor",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.helpers.entity",
        "homeassistant.helpers.entity_platform",
        f"{package_name}.call_state",
        f"{package_name}.runtime",
    )
    restored = {name: sys.modules.get(name) for name in module_names}

    class SensorEntity:
        pass

    def install(name, **attrs):
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        sys.modules[name] = module

    install(
        "homeassistant.components.sensor",
        SensorDeviceClass=types.SimpleNamespace(ENUM="enum"),
        SensorEntity=SensorEntity,
    )
    install("homeassistant.config_entries", ConfigEntry=object)
    install("homeassistant.core", HomeAssistant=object)
    install(
        "homeassistant.helpers.entity",
        EntityCategory=types.SimpleNamespace(DIAGNOSTIC="diagnostic"),
    )
    install(
        "homeassistant.helpers.entity_platform", AddEntitiesCallback=object
    )
    install(f"{package_name}.call_state", CALL_STATES=("idle",))
    install(f"{package_name}.runtime", ComelitRingRuntime=object)
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.sensor_readback_{uuid4().hex}",
        ROOT / "custom_components/comelit/sensor.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in restored.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_ordered_episode_records_ring_ack_rtp_exit_and_lifecycle() -> None:
    ledger, clock = _ledger()
    ledger.note_media_start(1)
    clock.value += 0.125
    for line in (
        "V4_RING_KIND=CALL_INIT",
        "SECOND_001A_RESPONSE=STRUCTURAL_ACK",
        "SECOND_001A_ACK_CLASSIFICATION=STATE_SCOPED_STRUCTURAL",
        "REFRESH_FAIL_CLOSED=true",
        "P80_VIDEO_RTP_PACKETS=7",
        "P80_VIDEO_RTP_PACKETS=8",
    ):
        ledger.observe_native_line(line, 1)
    ledger.note_native_exit(0, 1)
    ledger.note_stop_reason("last_lease_released", 1)
    ledger.note_teardown(True, 1)
    ledger.note_listener_resume(True, 1)

    snapshot = ledger.snapshot()
    episode = snapshot["episodes"][0]
    assert episode["generation"] == 1
    assert episode["episode_id"] == 1
    assert episode["ring_observed_offset_ms"] == 125
    assert episode["second_001a_response"] == "STRUCTURAL_ACK"
    assert episode["ack_classification"] == "STATE_SCOPED_STRUCTURAL"
    assert episode["refresh_fail_closed"] is True
    assert episode["last_video_rtp_packets"] == 8
    assert episode["video_progress_after_ring"] is True
    assert episode["native_exit_code"] == 0
    assert episode["stop_reason"] == "last_lease_released"
    assert episode["teardown_confirmed"] is True
    assert episode["listener_resumed"] is True
    assert episode["sealed"] is True
    assert episode["seal_reason"] == "listener_resumed"
    assert snapshot["active_episode_id"] is None
    assert snapshot["unattributed"] == 0
    assert snapshot["production_effect"] is False
    assert snapshot["protocol_write_performed"] is False


def test_out_of_order_and_duplicate_events_do_not_regress_counters() -> None:
    ledger, _ = _ledger()
    ledger.note_media_start(1)
    ledger.observe_native_line("P80_VIDEO_RTP_PACKETS=9", 1)
    # A late, lower counter must not move the high-water mark backwards.
    ledger.observe_native_line("P80_VIDEO_RTP_PACKETS=3", 1)
    ledger.observe_native_line("V4_RING_KIND=CALL_INIT", 1)
    ledger.observe_native_line("SECOND_001A_RESPONSE=AMBIGUOUS", 1)
    ledger.observe_native_line("SECOND_001A_RESPONSE=ABSENT", 1)
    ledger.observe_native_line("P80_VIDEO_RTP_PACKETS=10", 1)

    episode = ledger.snapshot()["episodes"][0]
    assert episode["last_video_rtp_packets"] == 10
    assert episode["second_001a_response"] == "ABSENT"
    assert episode["video_progress_after_ring"] is True
    # Packet growth before the Ring marker must not count as post-Ring progress.
    assert ledger.snapshot()["events"][1]["kind"] == "P80_VIDEO_RTP_PACKETS"


def test_default_is_not_observed_not_absent() -> None:
    ledger, _ = _ledger()
    ledger.note_media_start(1)
    episode = ledger.snapshot()["episodes"][0]
    assert episode["second_001a_response"] is None
    assert episode["ack_classification"] is None
    assert episode["refresh_fail_closed"] is None
    ledger.observe_native_line("SECOND_001A_RESPONSE=ABSENT", 1)
    assert ledger.snapshot()["episodes"][0]["second_001a_response"] == "ABSENT"


def test_generation_isolation_rejects_stale_callbacks_after_new_episode() -> None:
    ledger, _ = _ledger()
    ledger.note_media_start(1)
    ledger.observe_native_line("V4_RING_KIND=CALL_INIT", 1)
    ledger.observe_native_line("P80_VIDEO_RTP_PACKETS=5", 1)
    ledger.note_listener_resume(True, 1)

    ledger.note_media_start(2)
    ledger.observe_native_line("P80_VIDEO_RTP_PACKETS=1", 2)
    before = repr(ledger.snapshot()["episodes"][1])

    # Delayed callbacks from the sealed generation must not touch episode B.
    ledger.observe_native_line("V4_RING_KIND=CALL_INIT", 1)
    ledger.observe_native_line("P80_VIDEO_RTP_PACKETS=99", 1)
    ledger.note_native_exit(7, 1)
    ledger.note_teardown(True, 1)
    ledger.note_listener_resume(True, 1)

    snapshot = ledger.snapshot()
    assert repr(snapshot["episodes"][1]) == before
    assert snapshot["episodes"][1]["episode_id"] == 2
    assert snapshot["unattributed"] == 5
    assert snapshot["active_episode_id"] == 2


def test_owner_restart_seals_previous_episode_as_replaced() -> None:
    ledger, _ = _ledger()
    ledger.note_media_start(1)
    ledger.observe_native_line("V4_RING_KIND=CALL_INIT", 1)
    ledger.note_media_start(2)
    first = ledger.snapshot()["episodes"][0]
    assert first["sealed"] is True
    assert first["seal_reason"] == "replaced"
    assert ledger.snapshot()["episodes"][1]["sealed"] is False


def test_same_door_reuse_and_media_start_failure_are_accounted() -> None:
    ledger, _ = _ledger()
    ledger.note_media_start(1)
    ledger.note_listener_resume(True, 1)
    ledger.note_media_start(1)  # same generation value is still a new episode
    ledger.note_media_start(-1)  # invalid generation fails closed
    assert ledger.snapshot()["dropped_invalid"] == 1
    episodes = ledger.snapshot()["episodes"]
    assert [episode["episode_id"] for episode in episodes] == [1, 2]
    assert episodes[1]["generation"] == 1


def test_no_ring_observed_and_stop_before_ring_are_distinguishable() -> None:
    ledger, _ = _ledger()
    ledger.note_media_start(1)
    ledger.note_stop_reason("idle_timeout", 1)
    ledger.note_teardown(True, 1)
    ledger.note_listener_resume(True, 1)
    episode = ledger.snapshot()["episodes"][0]
    assert episode["ring_observed_offset_ms"] is None
    assert episode["video_progress_after_ring"] is False
    assert episode["stop_reason"] == "idle_timeout"


def test_double_callback_after_seal_is_rejected_not_mutating() -> None:
    ledger, _ = _ledger()
    ledger.note_media_start(1)
    ledger.note_teardown(True, 1)
    ledger.note_listener_resume(True, 1)
    sealed = repr(ledger.snapshot()["episodes"][0])
    ledger.note_listener_resume(False, 1)
    ledger.note_teardown(False, 1)
    assert repr(ledger.snapshot()["episodes"][0]) == sealed
    assert ledger.snapshot()["unattributed"] == 2


def test_zero_and_over_limit_counters_have_exact_accounting() -> None:
    ledger, _ = _ledger(max_episodes=1, max_events=1)
    ledger.note_media_start(1)
    ledger.note_media_start(2)
    ledger.note_media_start(3)
    snapshot = ledger.snapshot()
    assert len(snapshot["episodes"]) == 1
    assert snapshot["accounting"] == {
        "episodes_seen_total": 3,
        "episodes_evicted": 2,
        "events_seen_total": 5,
        "events_evicted": 4,
        "dropped_invalid": 0,
        "unattributed": 0,
    }


def test_payload_is_redacted_and_bad_observation_is_contained() -> None:
    ledger, _ = _ledger()
    ledger.note_media_start(1)
    ledger.observe_native_line("VIP_TOKEN=top-secret", 1)
    ledger.observe_native_line(object(), 1)
    rendered = repr(ledger.snapshot())
    assert "top-secret" not in rendered
    assert ledger.snapshot()["accounting"]["dropped_invalid"] == 1


def test_hook_contains_diagnostic_exceptions_and_latches() -> None:
    class BrokenController:
        def observe_native_line(self, owner, line, generation=None):
            raise RuntimeError("diagnostic failure")

    hook = ring_shadow.RingShadowHook(BrokenController(), MEDIA)
    for _ in range(ring_shadow.SHADOW_FAILURE_LATCH_LIMIT):
        hook.observe_line("P80_MEDIA_ACTIVE=true")
    assert hook.latched is True


def test_real_hook_controller_ledger_wiring_end_to_end() -> None:
    """Exercise the real RingShadowHook/Controller entrypoints used by the
    transport reader and media session, including generation propagation."""
    ledger, _ = _ledger()
    controller = ring_shadow.RingShadowController()
    controller.attach_ring_episode(ledger)
    hook = ring_shadow.RingShadowHook(controller, MEDIA)

    hook.note_state("media_transport_start")
    hook.observe_line("V4_RING_KIND=CALL_INIT")
    hook.observe_line("P80_VIDEO_RTP_PACKETS=4")
    hook.observe_line("P80_VIDEO_RTP_PACKETS=5")
    hook.note_native_exit(0)
    hook.note_stop_reason("shutdown")
    hook.note_teardown(True)
    hook.note_listener_resume(True)

    snapshot = ledger.snapshot()
    episode = snapshot["episodes"][0]
    assert episode["generation"] == 1
    assert episode["ring_observed_offset_ms"] is not None
    assert episode["video_progress_after_ring"] is True
    assert episode["native_exit_code"] == 0
    assert episode["teardown_confirmed"] is True
    assert episode["listener_resumed"] is True
    assert episode["sealed"] is True


def test_listener_sensor_reads_sealed_episode_via_supervisor_snapshot_view() -> None:
    """Integrated HA readback: real controller/ledger -> supervisor -> sensor."""

    class Runtime:
        running = False
        listener_ready = False
        attached_media_busy = False

        def status(self):
            return {
                "running": False,
                "listener_ready": False,
                "last_error": None,
                "last_native_exit_code": None,
                "last_native_failure_markers": (),
                "media_diagnostics": (
                    media_diagnostics.MediaCallDiagnostics().snapshot()
                ),
            }

    class Entry:
        def async_create_background_task(self, hass, coro, name):
            raise AssertionError("background task is not part of readback")

    class Listener:
        media_paused = False
        attached_media_busy = False
        listener_ready = False

        def __init__(self, supervisor):
            self.supervisor = supervisor

        async def async_pause_for_media(self):
            self.media_paused = True
            self.listener_ready = False

        async def async_resume_after_media(self):
            self.media_paused = False
            self.listener_ready = True
            # Exercise the real supervisor state entrypoint. READY is
            # published before the media lifecycle records/seals resume.
            self.supervisor._set_state(supervisor_module.LISTENER_STATE_READY)

    class Transport:
        def __init__(self, controller):
            self.active = False
            self.hook = ring_shadow.RingShadowHook(controller, MEDIA)

        async def async_start(self, panel):
            self.hook.note_state("media_transport_start")
            self.active = True

        async def async_stop(self):
            self.hook.note_native_exit(0)
            self.active = False

    ledger, _ = _ledger()
    controller = ring_shadow.RingShadowController()
    controller.attach_ring_episode(ledger)
    supervisor_module = _load_component_module(str(ROOT), "supervisor")
    supervisor = supervisor_module.ComelitRuntimeSupervisor(
        object(), Runtime(), entry=Entry(), ring_shadow=controller
    )
    media_session_module = _load_component_module(str(ROOT), "media_session")
    listener = Listener(supervisor)
    transport = Transport(controller)
    manager = media_session_module.ComelitMediaSessionManager(
        listener,
        transport,
        ring_shadow=controller,
        diagnostic_status_notify=getattr(
            supervisor, "notify_diagnostic_status", None
        ),
    )
    publications = []

    def capture_terminal_publication():
        snapshot = ledger.snapshot()
        publications.append(
            (
                manager.phase,
                listener.listener_ready,
                snapshot["episodes"][-1]["sealed"],
            )
        )

    supervisor.async_add_status_listener(capture_terminal_publication)

    async def exercise():
        await manager.async_acquire(panel="entrance", reason="wiring_test")
        for line in (
            "V4_RING_PHASE=INITIAL",
            "V4_RING_KIND=CALL_INIT",
            "SECOND_001A_RESPONSE=STRUCTURAL_ACK",
            "SECOND_001A_ACK_CLASSIFICATION=STATE_SCOPED_STRUCTURAL",
            "REFRESH_FAIL_CLOSED=false",
            "P80_VIDEO_RTP_PACKETS=0",
            "P80_VIDEO_RTP_PACKETS=3",
        ):
            transport.hook.observe_line(line)
        # A realistic call produces far more progress markers than the HA
        # projection budget.  Its compact sealed evidence must retain the
        # beginning of the Ring -> 001A -> RTP ordering.
        for count in range(50, 2050, 50):
            transport.hook.observe_line(f"P80_VIDEO_RTP_PACKETS={count}")
        await manager.async_release(reason="wiring_test")

    asyncio.run(exercise())
    # READY is published before sealing; the dedicated terminal update then
    # makes the sealed evidence readable. RTP progress emits no HA update.
    assert publications == [
        ("stopping", True, False),
        ("inactive", True, True),
    ]

    # The legacy snapshot deliberately has no ledger.  This assertion makes
    # the test fail if supervisor readback regresses from snapshot_view().
    assert "ring_episode" not in controller.snapshot()
    assert controller.snapshot_view()["ring_episode"]["episodes"]

    sensor_module = _load_sensor_module(supervisor_module)
    sensor = sensor_module.ComelitListenerStatusSensor(supervisor)
    attributes = sensor.extra_state_attributes
    projection = attributes["ring_episode"]
    assert projection
    assert len(projection["episodes"]) == 1
    episode = projection["episodes"][0]
    assert episode["sealed"] is True
    assert episode["seal_reason"] == "listener_resumed"
    assert episode["ring_observed_offset_ms"] is not None
    assert episode["owner_kind"] == MEDIA
    assert episode["ring_marker"] == "CALL_INIT"
    assert isinstance(episode["last_event_seq"], int)
    assert isinstance(episode["last_event_offset_ms"], int)
    assert episode["second_001a_response"] == "STRUCTURAL_ACK"
    assert episode["ack_classification"] == "STATE_SCOPED_STRUCTURAL"
    assert episode["video_progress_after_ring"] is True
    assert episode["native_exit_code"] == 0
    assert episode["teardown_confirmed"] is True
    assert episode["listener_resumed"] is True
    event_kinds = [event["kind"] for event in projection["events"]]
    assert event_kinds == [
        "MEDIA_START",
        "CALL_INIT",
        "SECOND_001A_RESPONSE",
        "SECOND_001A_ACK_CLASSIFICATION",
        "REFRESH_FAIL_CLOSED",
        "P80_VIDEO_RTP_PACKETS",
        "P80_VIDEO_RTP_PACKETS",
        "STOP_REASON",
        "NATIVE_EXIT",
        "TEARDOWN",
        "LISTENER_RESUME",
        "SEAL",
    ]
    assert [event["value"] for event in projection["events"][5:7]] == [0, 2000]

    # A newer open media generation must not replace or mutate TEST B's last
    # sealed evidence in HA readback.
    sealed_evidence = json.dumps(
        {"episodes": projection["episodes"], "events": projection["events"]},
        sort_keys=True,
        default=list,
    )
    transport.hook.note_state("media_transport_start")
    for count in range(0, 2050, 50):
        transport.hook.observe_line(f"P80_VIDEO_RTP_PACKETS={count}")
    after_new_generation = sensor.extra_state_attributes["ring_episode"]
    assert json.dumps(
        {
            "episodes": after_new_generation["episodes"],
            "events": after_new_generation["events"],
        },
        sort_keys=True,
        default=list,
    ) == sealed_evidence
    rendered = repr(attributes)
    for forbidden in (
        "V4_RING_BODY_32_35",
        "V4_RING_FRAME_SHA256",
        "VIP_TOKEN",
        "top-secret",
    ):
        assert forbidden not in rendered
    assert attributes["media_diagnostics"] is not None
    assert len(json.dumps(attributes, default=list).encode("utf-8")) < 8192


def test_wiring_call_sites_are_present_and_lifecycle_never_consults_ledger() -> None:
    session = (ROOT / "custom_components/comelit/media_session.py").read_text(encoding="utf-8")
    transport = (ROOT / "custom_components/comelit/media_transport.py").read_text(encoding="utf-8")
    shadow = (ROOT / "custom_components/comelit/ring_shadow.py").read_text(encoding="utf-8")

    # Real production entrypoints that must feed the ledger.
    assert "self._capture_native_failure(process.returncode)" in transport
    assert "hook.note_native_exit(returncode)" in transport
    assert 'note_stop_reason("shutdown")' in session
    assert "note_teardown(True)" in session
    assert "note_listener_resume(True)" in session
    assert "note_media_start(self._owner_generation[owner])" in shadow
    assert "line, self._owner_generation.get(owner, 0)" in shadow

    # Production must never read diagnostics to decide behaviour.
    assert "ring_episode.snapshot" not in session
    assert "ring_episode.snapshot" not in transport
    assert "comelit_ring" not in shadow


def test_static_shadow_module_remains_dependency_free() -> None:
    source = (ROOT / "custom_components/comelit/ring_shadow.py").read_text(encoding="utf-8")
    assert "ring_episode" not in source.split("SHADOW_OWNER_LISTENER", 1)[0]
