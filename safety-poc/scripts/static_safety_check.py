#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "comelit_safety_poc"
python_files = sorted(SRC.glob("*.py"))

banned_import_roots = {"socket", "http", "urllib", "requests", "aiohttp", "subprocess", "ssl"}
# ct120_real_session.py launches the pinned native wrapper. p14_ha_bridge.py is
# the only additional sanctioned process boundary: it may invoke exactly the
# canonical p13_one_shot_physical_runner.sh with locally pinned arguments after
# HMAC/replay validation. Dedicated P14 tests pin that command shape and prove
# that no network-supplied shell/target/retry parameters are exposed.
allowed_subprocess_modules = {"ct120_real_session.py", "p14_ha_bridge.py"}
banned_literals = [
    "http://", "https://", "/servicerest/", "64100", "api.comelitgroup.com",
    "IconaBridgeClient", ".open_door(", "OPEN_DOOR_INIT", "OPEN_DOOR_CONFIRM", "OPEN_DOOR =", "create_door_message",
]

bad_imports: dict[str, list[str]] = {}
bad_literals: dict[str, list[str]] = {}

for path in python_files:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])

    found_imports = sorted(imports & banned_import_roots)
    if path.name in allowed_subprocess_modules:
        found_imports = [x for x in found_imports if x != "subprocess"]
    found_literals = [x for x in banned_literals if x in text]
    if found_imports:
        bad_imports[path.name] = found_imports
    if found_literals:
        bad_literals[path.name] = found_literals

if bad_imports or bad_literals:
    print(f"STATIC_SAFETY_CHECK=FAIL imports={bad_imports} literals={bad_literals}")
    raise SystemExit(1)

print("STATIC_SAFETY_CHECK=PASS")
print("NETWORK_IMPORTS_PRESENT=false")
print("COMELIT_ENDPOINTS_PRESENT=false")
print(f"SOURCE_FILES_SCANNED={len(python_files)}")
