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
    handler = card.split('cameraToggle.addEventListener("click"', 1)[1].split(
        "this._intercomViewerOpen = !this._intercomViewerOpen", 1
    )[0]
    guard = 'if (this._intercomViewerMode === "ended")'
    assert guard in handler
    # Only the ended branch itself: the next block has the same mode reset.
    branch = handler.split(guard, 1)[1].split("\n        }", 1)[0]
    assert 'this._intercomViewerMode = "webcodecs"' in branch
    assert "this._intercomViewerOpen = true" in branch
    assert branch.index("this._intercomViewerOpen = true") < branch.rindex("return;")
    assert card.count("Открыть камеру заново") >= 2


def _intercom_toggle_body() -> str:
    card = _card()
    return card.split("[data-intercom-camera-toggle]", 1)[1].split(
        "_renderSurveillance", 1
    )[0]


def test_reopen_waits_for_the_media_manager_to_confirm_the_release():
    card = _card()
    presentation = card.split("_cameraPresentation(model) {", 1)[1].split(
        "_intercomChannelBusy(model)", 1
    )[0]

    # The media manager is the authority, not the viewer EOS.  Both the lease
    # flag and the transition phase are consulted.
    assert "attributes.media_active === true" in presentation
    assert '"starting", "active", "stopping"' in presentation
    assert "String(attributes.media_phase || \"\")" in presentation

    busy = card.split("_intercomChannelBusy(model) {", 1)[1].split("\n  }", 1)[0]
    assert 'this._intercomViewerMode !== "ended" && this._intercomViewerOpen' in busy

    # Every toggle surface (initial template and in-place refresh) is gated,
    # and the label explains the wait instead of promising an open.
    assert "intercomChannelBusy" in card
    assert 'camera.available && !intercomChannelBusy ? "" : "disabled"' in card
    assert "cameraToggle.disabled = !camera.available || channelBusy;" in card
    assert "Освобождение канала…" in card

    # No fixed delay and no blind retry: re-arming comes from state updates.
    assert "setTimeout" not in card


def test_reopen_click_is_refused_while_the_channel_is_still_released():
    card = _card()
    handler = card.split('cameraToggle.addEventListener("click"', 1)[1].split(
        "this._intercomViewerOpen = !this._intercomViewerOpen", 1
    )[0]
    guard = "if (this._intercomChannelBusy(model)) {"
    assert guard in handler
    # The guard runs before any branch that could start a viewer.
    assert handler.index(guard) < handler.index('this._intercomViewerMode === "ended"')
    assert "Never start\n          // a second session" in handler


def test_busy_reopen_never_falls_back_to_a_second_stream():
    card = _card()
    terminal = card.split('viewer.addEventListener("comelit-webcodecs-terminal"', 1)[
        1
    ].split("if (\n      generation !== this._intercomViewerGeneration", 1)[0]
    assert 'this._intercomViewerFallbackReason === "intercom_media_busy"' in terminal
    assert "this._showIntercomChannelBusy(generation);" in terminal
    # The busy branch returns before the legacy HLS fallback is reachable.
    assert terminal.index("_showIntercomChannelBusy(generation)") < terminal.index(
        "_showIntercomLegacyFallback(generation)"
    )
    busy_notice = card.split("_intercomEndedNotice() {", 1)[1].split("\n  }", 1)[0]
    assert 'data-ended-reason="intercom_media_busy"' in busy_notice
    assert 'data-ended-reason="call_handoff"' in busy_notice


def test_ha_updates_tab_switches_and_reload_never_start_a_viewer():
    card = _card()

    # A controller reload (F5) re-instantiates the card closed: nothing is
    # persisted, and the configuration path resets to the closed default.
    assert "localStorage" not in card
    assert "sessionStorage" not in card
    assert "this._intercomViewerOpen = false;" in card

    hass_setter = card.split("set hass(hass) {", 1)[1].split("\n  }", 1)[0]
    assert "_updateDynamicState();" in hass_setter
    assert "_mountIntercomViewer" not in hass_setter

    dynamic = card.split("_updateDynamicState() {", 1)[1].split("\n  }", 1)[0]
    assert "_mountIntercomViewer" not in dynamic

    # A full render preserves a healthy viewer instead of replacing its node.
    assert "this._canPreserveIntercomWebCodecsViewer()" in card
    assert "// Home Assistant state refreshes and semantically unchanged card renders" in card

    # Auto-start belongs to the mount path only.
    mount = card.split("_mountIntercomWebCodecsViewer(target, camera, generation) {", 1)[
        1
    ].split("\n  }", 1)[0]
    assert "viewer.autoStart = true;" in mount
    assert card.count("viewer.autoStart = true;") == 2  # intercom + surveillance
