from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "custom_components/comelit/frontend/comelit-card.js"


def _card() -> str:
    return CARD.read_text(encoding="utf-8")


def test_gate_is_the_only_cross_panel_action_allowed_during_entrance_call():
    card = _card()

    assert "_panelLockedByCall(panel, call)" in card
    assert 'panel === "gate"' in card
    assert 'call.panel === "entrance"' in card
    assert "!gateDuringEntranceCall" in card

    # The one-way exception must drive every frontend lock surface: visual
    # panel state, door-action presentation, initial render, and panel click.
    assert "this._panelLockedByCall(panelId, call)" in card
    assert "const lockedByCall = this._panelLockedByCall(panel, call);" in card
    assert 'const entranceLocked = this._panelLockedByCall("entrance", call);' in card
    assert 'const gateLocked = this._panelLockedByCall("gate", call);' in card
    assert "if (this._panelLockedByCall(panel, call))" in card


def test_gate_cross_panel_exception_does_not_bypass_backend_door_safety():
    card = _card()

    # Gate remains disabled when the HA entity says ordinary presses are not
    # allowed or while an explicit press is already in flight. The frontend
    # only removes the obsolete call-panel lock; backend policy stays final.
    assert "state.attributes?.standard_press_allowed === true" in card
    assert "disabled: !pressAllowed || lockedByCall || inFlight" in card
    assert 'await this._hass.callService("button", "press", {' in card
    assert "No automatic retry is allowed here." in card


def test_ended_intercom_viewer_is_not_remounted_until_the_user_reopens():
    card = CARD.read_text(encoding="utf-8")
    mount = card.split("async _mountIntercomViewer()", 1)[1]
    body = mount.split("_mountIntercomWebCodecsViewer", 1)[0]
    assert 'this._intercomViewerMode === "ended"' in body
    assert "data-call-handoff" in body
    # The ended notice must be rendered before any new viewer is created.
    assert body.index('_intercomViewerMode === "ended"') < body.index(
        "++this._intercomViewerGeneration"
    )


def test_ended_viewer_reopens_with_one_click():
    card = CARD.read_text(encoding="utf-8")
    toggle = card.split('if (cameraToggle) {', 1)[1].split('const camera = this._cameraPresentation(model);', 1)[1]
    handler = card.split('cameraToggle.addEventListener("click"', 1)[1].split('});', 1)[0]
    assert 'this._intercomViewerMode === "ended"' in handler
    assert "this._intercomViewerOpen = true" in handler
    assert "Открыть камеру заново" in card
