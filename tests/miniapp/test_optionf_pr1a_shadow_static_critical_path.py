from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SHADOW_PATH = ROOT / "custom_components" / "comelit" / "ring_shadow.py"


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
