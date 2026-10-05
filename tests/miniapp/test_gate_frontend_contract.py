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
