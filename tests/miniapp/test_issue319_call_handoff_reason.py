from __future__ import annotations

import ast
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
    # The attached viewer shares the listener's call, so its end is explained.
    assert reason("source_eof", kind="attached", ring_handoff=True) == "call_handoff"
    assert reason("source_eof", kind="attached", ring_handoff=False) == "source_eof"
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


def test_exit_error_is_normal_only_when_real_pyav_handoff_is_confirmed():
    webcodecs = _load(
        "comelit_webcodecs_expected_handoff_exit",
        ROOT / "custom_components/comelit/miniapp/webcodecs.py",
    )

    av_exit_type = type("ExitError", (Exception,), {"__module__": "av.error"})
    interrupted = av_exit_type(
        "Immediate exit requested: '/run/comelit-media/local-rtp.sdp'"
    )
    assert webcodecs.is_expected_pyav_handoff_exit(interrupted, handoff=True)
    assert not webcodecs.is_expected_pyav_handoff_exit(
        interrupted, handoff=False
    )
    assert not webcodecs.is_expected_pyav_handoff_exit(
        av_exit_type("unrelated demux failure"), handoff=True
    )
    foreign_error = type("ExitError", (Exception,), {"__module__": "other"})
    assert not webcodecs.is_expected_pyav_handoff_exit(
        foreign_error("Immediate exit requested"), handoff=True
    )
    assert not webcodecs.is_expected_pyav_handoff_exit(
        RuntimeError("Immediate exit requested"), handoff=True
    )


def test_webcodecs_summary_emitted_from_handler_cleanup_finally():
    """A cancellation in release/child join must not skip SUMMARY."""
    source = (
        ROOT / "custom_components/comelit/miniapp/views.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    klass = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "MiniAppCameraWebCodecsView"
    )
    method = next(
        node for node in klass.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get"
    )
    summaries = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "webcodecs_summary_line"
    ]
    assert len(summaries) == 1, "exactly one summary per handler"
    assert any(
        summaries[0] in set(
            nested
            for block in candidate.finalbody
            for nested in ast.walk(block)
        )
        for candidate in ast.walk(method)
        if isinstance(candidate, ast.Try)
        and candidate.finalbody
        and any(
            isinstance(handler.type, ast.Attribute)
            and handler.type.attr == "CancelledError"
            for handler in candidate.handlers
        )
    ), "summary must run even if the teardown CancelledError handler raises"
