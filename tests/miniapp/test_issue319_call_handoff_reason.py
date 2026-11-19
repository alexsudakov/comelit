from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_entrance_eos_reason_rewrites_only_the_session_end():
    webcodecs = _load(
        "comelit_webcodecs_under_test",
        ROOT / "custom_components/comelit/miniapp/webcodecs.py",
    )
    reason = webcodecs.entrance_eos_reason
    assert reason("source_eof", kind="entrance", ring_handoff=True) == "call_handoff"
    assert reason("source_eof", kind="entrance", ring_handoff=False) == "source_eof"
    assert reason("source_eof", kind="ordinary", ring_handoff=True) == "source_eof"
    assert (
        reason(
            "attached_webcodecs_source_failed", kind="entrance", ring_handoff=True
        )
        == "attached_webcodecs_source_failed"
    )


def test_call_handoff_is_a_valid_summary_reason():
    webcodecs = _load(
        "comelit_webcodecs_under_test",
        ROOT / "custom_components/comelit/miniapp/webcodecs.py",
    )
    line = webcodecs.webcodecs_summary_line(
        "camera.comelit_entrance",
        units=3,
        keyframes=1,
        bytes_sent=10,
        errors=0,
        reason="call_handoff",
    )
    assert "reason=call_handoff" in line
