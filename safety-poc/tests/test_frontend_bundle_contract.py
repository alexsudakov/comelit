from __future__ import annotations

import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
CARD = REPO_ROOT / "custom_components" / "comelit" / "frontend" / "comelit-card.js"
INIT = REPO_ROOT / "custom_components" / "comelit" / "__init__.py"
MANIFEST = REPO_ROOT / "custom_components" / "comelit" / "manifest.json"


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

    def test_surveillance_mvp_does_not_issue_ha_service_actions(self) -> None:
        source = CARD.read_text(encoding="utf-8")

        self.assertNotIn(".callService(", source)
        self.assertNotIn(".call_service(", source)

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
        self.assertEqual(manifest["version"], "1.5.14")


if __name__ == "__main__":
    unittest.main()
