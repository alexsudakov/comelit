from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "custom_components" / "comelit" / "frontend" / "miniapp" / "host.js"
WORKFLOW = ROOT / ".github" / "workflows" / "miniapp.yml"
REMOVED_SUITE = ROOT / "tests" / "miniapp" / "webrtc.scenarios.browser.cjs"


def test_flaky_browser_suite_is_removed_and_unreferenced() -> None:
    assert not REMOVED_SUITE.exists()
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "webrtc.scenarios.browser.cjs" not in workflow
    assert "Verify WebRTC and HLS diagnostics scenarios" not in workflow


def test_attached_viewer_heartbeat_lease_contract() -> None:
    source = HOST.read_text(encoding="utf-8")
    assert re.search(r"const ATTACHED_VIEWER_HEARTBEAT_MS = 5000;", source)
    assert "_attachedViewerHeartbeatTimer = setInterval(" in source
    assert 'this._sendAttachedViewerEvent("heartbeat")' in source
    assert "if (this._attachedViewerOpen && this.isConnected)" in source
    assert 'window.addEventListener("pagehide", this._attachedViewerPagehideHandler);' in source
    assert 'window.addEventListener("visibilitychange"' not in source


def test_webrtc_hls_fallback_reason_contract() -> None:
    source = HOST.read_text(encoding="utf-8")
    for reason in (
        "stats_deadline_checking",
        "stats_deadline_other",
        "ice_failed",
        "connection_failed",
        "offer_error",
        "answer_error",
        "candidate_error",
        "websocket_closed",
        "navigate",
    ):
        assert f'"{reason}"' in source
    assert re.search(r"\}, 6000\);", source)
