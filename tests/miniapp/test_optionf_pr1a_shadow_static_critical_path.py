from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SHADOW_PATH = ROOT / "custom_components" / "comelit" / "ring_shadow.py"


_CHECKER_REQUIRED_SOURCE = """
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Deque

class RingShadowHook:
    def observe_line(self, line): self._invoke("observe_native_line", line)
    def note_state(self, state): self._invoke("note_state", state)
    def _invoke(self, method, *args): return None

class RingShadowController:
    def observe_native_line(self, owner, line): return None
    def note_state(self, owner, state): return None
    def note_watchdog_boundary_crossed(self, owner): return None

class RingMarkerBatcher:
    def observe(self, line):
        {observe_body}

class RingEmitGuard:
    def decide(self): return None
"""


def test_static_critical_path_check_passes():
    result = subprocess.run(
        [sys.executable, "scripts/static_shadow_critical_path_check.py"],
        cwd=ROOT / "safety-poc",
        check=True,
        text=True,
        capture_output=True,
    )
    output = result.stdout
    assert "STATIC_SHADOW_CRITICAL_PATH_CHECK=PASS" in output
    for flag in (
        "CRITICAL_PATH_AWAIT=false",
        "CRITICAL_PATH_SLEEP=false",
        "CRITICAL_PATH_NETWORK_IO=false",
        "CRITICAL_PATH_FILE_IO=false",
        "CRITICAL_PATH_SUBPROCESS=false",
        "CRITICAL_PATH_UNBOUNDED_STORAGE=false",
    ):
        assert flag in output


def test_shadow_module_import_allowlist():
    tree = ast.parse(SHADOW_PATH.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert imports == {"__future__", "collections", "dataclasses", "typing"}


def test_shadow_module_has_no_unbounded_collections():
    tree = ast.parse(SHADOW_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            assert name not in {"list", "set", "dict", "Counter"}
            if name == "deque":
                assert any(keyword.arg == "maxlen" for keyword in node.keywords)


def _run_checker_for_source(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    module_path = tmp_path / "candidate_shadow.py"
    module_path.write_text(source, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "scripts/static_shadow_critical_path_check.py",
            str(module_path),
        ],
        cwd=ROOT / "safety-poc",
        text=True,
        capture_output=True,
        check=False,
    )


def test_static_checker_rejects_non_literal_deque_maxlen(tmp_path):
    source = (
        "LIMIT = 1\n"
        + _CHECKER_REQUIRED_SOURCE.format(observe_body="items = deque(maxlen=LIMIT)")
    )
    result = _run_checker_for_source(tmp_path, source)
    assert result.returncode != 0
    assert "unbounded_storage_present" in result.stdout


def test_static_checker_rejects_append_on_non_deque_binding(tmp_path):
    source = _CHECKER_REQUIRED_SOURCE.format(
        observe_body="items = ()\n        items.append(line)"
    )
    result = _run_checker_for_source(tmp_path, source)
    assert result.returncode != 0
    assert "unbounded_storage_present" in result.stdout


def test_static_checker_rejects_missing_entrypoint(tmp_path):
    source = _CHECKER_REQUIRED_SOURCE.format(observe_body="return None").replace(
        "\nclass RingEmitGuard:\n    def decide(self): return None\n",
        "\n",
    )
    result = _run_checker_for_source(tmp_path, source)
    assert result.returncode != 0
    assert "missing_entrypoints" in result.stdout


def test_static_checker_visits_function_bodies_for_imports(tmp_path):
    source = _CHECKER_REQUIRED_SOURCE.format(
        observe_body="import os\n        return None"
    )
    result = _run_checker_for_source(tmp_path, source)
    assert result.returncode != 0
    assert "imports=['os']" in result.stdout
