from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import textwrap
import unittest

from manifest_version_contract import is_valid_release_version


REPO_ROOT = Path(__file__).resolve().parents[2]
CARD = REPO_ROOT / "custom_components" / "comelit" / "frontend" / "comelit-card.js"
INIT = REPO_ROOT / "custom_components" / "comelit" / "__init__.py"
MANIFEST = REPO_ROOT / "custom_components" / "comelit" / "manifest.json"


def _extract_js_method(source: str, name: str) -> str:
    start = source.index(f"{name}(")
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Could not extract JavaScript method {name}")


class FrontendBundleContractTest(unittest.TestCase):
    def test_card_uses_ha_registry_and_standard_live_camera_view(self) -> None:
        source = CARD.read_text(encoding="utf-8")

        self.assertIn('config/entity_registry/list', source)
        self.assertIn('config/label_registry/list', source)
        self.assertIn('type: "picture-entity"', source)
        self.assertIn('camera_view: "live"', source)
        self.assertIn('platform === "comelit"', source)
        self.assertIn('comelit_entrance_camera', source)

    def test_surveillance_mvp_has_no_raw_camera_or_protocol_secrets(self) -> None:
        source = CARD.read_text(encoding="utf-8").lower()

        for forbidden in (
            "rtsp://",
            "vip_token",
            "oauth_access_token",
            "refresh_token",
            "shared_secret",
            "device_uuid",
        ):
            self.assertNotIn(forbidden, source)

    def test_intercom_door_actions_use_only_semantic_ha_button_press(self) -> None:
        source = CARD.read_text(encoding="utf-8")

        self.assertIn('this._hass.callService("button", "press"', source)
        self.assertEqual(source.count(".callService("), 1)
        self.assertNotIn('callService("comelit"', source)
        self.assertNotIn("async_open_door", source)
        self.assertIn("No automatic retry is allowed here.", source)
        self.assertIn(
            "Физическое открытие не подтверждается интеграцией.",
            source,
        )

    def test_intercom_camera_view_is_explicit_and_uses_standard_ha_viewer(self) -> None:
        source = CARD.read_text(encoding="utf-8")

        self.assertIn("data-intercom-camera-toggle", source)
        self.assertIn('id="intercom-viewer"', source)
        self.assertIn("this._intercomViewerOpen", source)
        self.assertIn("async _mountIntercomViewer()", source)
        self.assertIn('camera_view: "live"', source)

    def test_intercom_viewer_parks_and_disconnects_across_tab_switches(self) -> None:
        source = CARD.read_text(encoding="utf-8")

        self.assertIn('data-tab-panel="intercom"', source)
        self.assertIn('data-tab-panel="surveillance"', source)
        self.assertIn("panel.hidden = panel.dataset.tabPanel !== nextTab", source)
        self.assertIn("async _parkAndDisconnectIntercomViewer()", source)
        self.assertIn("await viewer.parkEntrance()", source)
        self.assertIn(
            'const target = this.shadowRoot.querySelector("#intercom-viewer")',
            source,
        )
        self.assertIn("target.replaceChildren()", source)
        self.assertNotIn(
            'if (nextTab === "surveillance") {\n          this._intercomViewerOpen = false;',
            source,
        )

    def test_surveillance_viewer_is_released_when_leaving_surveillance(self) -> None:
        source = CARD.read_text(encoding="utf-8")

        self.assertIn(
            "Ordinary surveillance viewing is not persistent.",
            source,
        )
        self.assertIn('const target = this.shadowRoot.querySelector("#viewer")', source)
        self.assertIn("target.replaceChildren()", source)

    def test_active_call_locks_other_intercom_panel(self) -> None:
        source = CARD.read_text(encoding="utf-8")
        panel_lock_method = _extract_js_method(source, "_panelLockedByCall")

        self.assertIn("data-intercom-select", source)
        self.assertIn('data-door-action="entrance"', source)
        self.assertIn('data-door-action="gate"', source)
        self.assertIn("call.active", panel_lock_method)
        self.assertIn("Boolean(call.panel)", panel_lock_method)
        self.assertIn("call.panel !== panel", panel_lock_method)
        self.assertIn('panel === "gate"', panel_lock_method)
        self.assertIn('call.panel === "entrance"', panel_lock_method)
        self.assertIn("!gateDuringEntranceCall", panel_lock_method)
        self.assertIn(
            'panel.classList.toggle(\n        "call-locked",\n        this._panelLockedByCall(panelId, call),\n      );',
            source,
        )
        self.assertIn(
            "const lockedByCall = this._panelLockedByCall(panel, call);",
            source,
        )
        self.assertIn(
            'const entranceLocked = this._panelLockedByCall("entrance", call);',
            source,
        )
        self.assertIn(
            'const gateLocked = this._panelLockedByCall("gate", call);',
            source,
        )
        self.assertIn("if (this._panelLockedByCall(panel, call))", source)
        self.assertIn("state.attributes?.standard_press_allowed === true", source)
        self.assertIn("disabled: !pressAllowed || lockedByCall || inFlight", source)
        self.assertIn("No automatic retry is allowed here.", source)

        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required to evaluate the frontend lock helper")
        script = textwrap.dedent(
            f"""
            const component = {{
              {panel_lock_method}
            }};
            const cases = [
              ["gate is selectable during an entrance call", "gate", {{active: true, panel: "entrance"}}, false],
              ["entrance is locked during a gate call", "entrance", {{active: true, panel: "gate"}}, true],
              ["entrance stays selectable during an entrance call", "entrance", {{active: true, panel: "entrance"}}, false],
              ["gate stays selectable during a gate call", "gate", {{active: true, panel: "gate"}}, false],
              ["inactive call does not lock", "entrance", {{active: false, panel: "gate"}}, false],
              ["missing call panel does not lock", "entrance", {{active: true, panel: null}}, false],
            ];
            for (const [label, panel, call, expected] of cases) {{
              const actual = component._panelLockedByCall(panel, call);
              if (actual !== expected) {{
                throw new Error(`${{label}}: expected ${{expected}}, got ${{actual}}`);
              }}
            }}
            """
        )
        subprocess.run([node, "-e", script], check=True)

    def test_card_uses_authoritative_call_state_for_one_shot_focus(self) -> None:
        source = CARD.read_text(encoding="utf-8")

        self.assertIn('"comelit_call_state"', source)
        self.assertIn('call.state !== "ringing"', source)
        self.assertIn("call.eventId === this._focusedCallEventId", source)
        self.assertIn('this._activeTab = "intercom"', source)
        self.assertIn("ACTIVE_CALL_STATES", source)
        self.assertIn('data-intercom-panel="entrance"', source)
        self.assertIn('data-intercom-panel="gate"', source)

    def test_live_viewer_is_not_recreated_on_every_hass_update(self) -> None:
        source = CARD.read_text(encoding="utf-8")

        self.assertIn("this._viewerElement.hass = this._hass", source)
        self.assertIn("if (firstHass || !this._rendered)", source)

    def test_integration_serves_bundled_frontend_with_http_dependency(self) -> None:
        init_source = INIT.read_text(encoding="utf-8")
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

        self.assertIn("async_register_static_paths", init_source)
        self.assertIn("/api/comelit/frontend", init_source)
        self.assertIn("http", manifest["dependencies"])
        self.assertTrue(is_valid_release_version(manifest["version"]))


if __name__ == "__main__":
    unittest.main()
