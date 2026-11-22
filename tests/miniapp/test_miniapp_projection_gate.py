"""End-to-end regression: Mini App state projection -> host adapter -> Comelit Card.

The defect this pins (live acceptance 2026-11-21, stage A): the Mini App hands the
card a whitelisted projection of HA state, and that projection did not carry
``media_phase`` / ``media_active`` for the Comelit entrance camera.  The card then
failed closed with «Состояние канала неизвестно» and the camera could not be
opened at all, while the media manager reported an explicitly released channel.

The production card source is executed in Node against the projection the
controller actually produces, through the host.js adapter contract.  Full
``hass.states`` are never substituted for it: that substitution is what let the
defect pass the earlier contract test.  DOM rendering and real browser
mounting are out of scope here and stay covered by the browser canaries.
"""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = ROOT / "custom_components/comelit/frontend/comelit-card.js"
HOST = ROOT / "custom_components/comelit/frontend/miniapp/host.js"
CANARY = HERE / "projection_gate_harness.cjs"

ENTRANCE = "camera.comelit_entrance"
DRIVEWAY = "camera.driveway"
SPOOF = "camera.spoofed_entrance"

_RELEASED = {
    "friendly_name": "Entrance",
    "media_phase": "inactive",
    "media_active": False,
}


def _runtime_fixture():
    """The controller test module owns the only fake HA harness in this suite."""
    path = HERE / "test_controller_runtime.py"
    spec = importlib.util.spec_from_file_location(
        "_comelit_controller_runtime_fixture", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _projection(camera_attributes):
    """Run the real controller projection over one entrance-camera state."""
    fixture = _runtime_fixture()
    controller, hass = fixture._controller(surveillance_label="Outside")
    hass.states._values[ENTRANCE] = fixture.FakeState("idle", dict(camera_attributes))
    # A surveillance camera that carries the same attributes in HA: it must
    # still be projected through the narrow allowlist only.
    hass.states._values[DRIVEWAY] = fixture.FakeState(
        "idle",
        {
            "friendly_name": "Driveway",
            "media_phase": "inactive",
            "media_active": False,
            "entity_picture": "/secret/path",
        },
    )
    # A foreign camera that reuses the entrance unique_id but not the platform:
    # the widened allowlist is keyed on (platform, unique_id), not on the id
    # alone.
    hass.entity_registry.entities[SPOOF] = fixture.FakeRegistryEntry(
        SPOOF,
        "generic",
        "comelit_entrance_camera",
        labels={"outside"},
        original_name="Spoof",
    )
    hass.states._values[SPOOF] = fixture.FakeState(
        "idle",
        {
            "friendly_name": "Spoof",
            "media_phase": "inactive",
            "media_active": False,
        },
    )
    token, session = controller.sessions.create(424242, 12345678, now=1_800_000_000)
    assert token
    return controller.bootstrap(session), controller.state_payload()


def _run_card(cases, tmp_path):
    node = shutil.which("node")
    assert node is not None, "node is required by this repository's CI gate"
    fixture_path = tmp_path / "projection.json"
    fixture_path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    completed = subprocess.run(
        [node, str(CANARY), str(CARD), str(fixture_path)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr[-3000:]
    return json.loads(completed.stdout)


def _case(name, attributes):
    bootstrap, state = _projection(attributes)
    return {"name": name, "bootstrap": bootstrap, "state": state}


def test_projection_carries_the_release_attributes_for_the_entrance_camera():
    bootstrap, state = _projection(_RELEASED)

    for payload in (bootstrap, state):
        attributes = payload["states"][ENTRANCE]["attributes"]
        assert attributes["media_phase"] == "inactive"
        assert attributes["media_active"] is False
        assert attributes["friendly_name"] == "Entrance"
        # The projection must stay a projection.
        assert "secret_transport_detail" not in attributes


def test_surveillance_cameras_do_not_gain_media_attributes():
    bootstrap, state = _projection(_RELEASED)

    for payload in (bootstrap, state):
        attributes = payload["states"][DRIVEWAY]["attributes"]
        assert attributes == {"friendly_name": "Driveway"}
        assert "media_phase" not in attributes
        assert "media_active" not in attributes
        assert "entity_picture" not in attributes
        # Same unique_id as the entrance camera, different platform: still narrow.
        spoofed = payload["states"][SPOOF]["attributes"]
        assert spoofed == {"friendly_name": "Spoof"}


def test_host_adapter_contract_is_what_the_canary_mirrors():
    """Keeps the harness honest if host.js or the toggle render ever changes."""

    host = HOST.read_text(encoding="utf-8")
    assert "states: bootstrap.states || {}," in host
    assert 'message?.type === "config/entity_registry/list"' in host
    assert "return bootstrap.entity_registry || [];" in host

    card = CARD.read_text(encoding="utf-8")
    # The harness recomputes these two production lines from the card's own
    # predicates; they must stay the only thing that disables the toggle.
    assert "cameraToggle.disabled = !camera.available || channelLabel !== null;" in card
    assert 'camera.available && intercomChannelLabel === null ? "" : "disabled"' in card
    assert 'this._intercomViewerOpen = false;' in card


def test_card_opens_only_on_the_projected_release_state(tmp_path):
    blocked = [
        ("no attributes", {}),
        ("phase int", {"media_phase": 1, "media_active": False}),
        ("phase list", {"media_phase": ["inactive"], "media_active": False}),
        ("phase object", {"media_phase": {"phase": "inactive"}, "media_active": False}),
        ("active absent", {"media_phase": "inactive"}),
        ("active string", {"media_phase": "inactive", "media_active": "false"}),
        ("phase stopping", {"media_phase": "stopping", "media_active": False}),
        ("phase active", {"media_phase": "active", "media_active": True}),
        ("phase error", {"media_phase": "error", "media_active": False}),
    ]
    cases = [_case("released", _RELEASED)]
    cases += [_case(name, attributes) for name, attributes in blocked]
    results = {row["name"]: row for row in _run_card(cases, tmp_path)}

    released = results["released"]
    assert released["before"]["disabled"] is False, released
    assert released["before"]["text"] == "Показать камеру", released
    assert released["before"]["channelState"] == "idle", released
    # The periodic /state refresh must not drop the attributes again.
    assert released["after"] == released["before"], released
    assert released["registryError"] is None, released
    # Nothing opens by itself: the viewer stays closed on mount and on refresh.
    assert released["viewerOpen"] is False, released

    expected_labels = {
        "no attributes": "Состояние канала неизвестно",
        "phase int": "Состояние канала неизвестно",
        "phase list": "Состояние канала неизвестно",
        "phase object": "Состояние канала неизвестно",
        "active absent": "Состояние канала неизвестно",
        "active string": "Состояние канала неизвестно",
        "phase stopping": "Освобождение канала…",
        "phase active": "Освобождение канала…",
        "phase error": "Камера недоступна",
    }
    for name, label in expected_labels.items():
        row = results[name]
        assert row["before"]["disabled"] is True, (name, row)
        assert row["before"]["text"] == label, (name, row)
        assert row["after"] == row["before"], (name, row)
        # A disabled button must never open a stream by itself.
        assert row["viewerOpen"] is False, (name, row)
        assert row["registryError"] is None, (name, row)
