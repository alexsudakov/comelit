#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

EXPECTED_PROD_SHA = "531683e2409b2f0f16489f61757708b8c63f6c5892a09013192469b0f6f614c9"
EXPECTED_DIAG_SHA = "0e0ccdf11d752dcdff79d643e1d169827d2acf23c804879c25841b257907d608"
DIAG_BIN = Path("/root/comelit-door-reject-diag-build/comelit-v4-door-diag-musl")
DIAG_SRC = Path("/root/comelit-door-reject-diag-build/comelit-v4-persistent-ring-door-diag.c")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}=FAIL anchor_count={count}")
    print(f"{label}=PASS")
    return text.replace(old, new, 1)


def main() -> int:
    repo = Path(__file__).resolve().parents[3]
    runtime_path = repo / "custom_components/comelit/runtime.py"
    button_path = repo / "custom_components/comelit/button.py"
    manifest_path = repo / "custom_components/comelit/manifest.json"
    native_path = repo / "custom_components/comelit/native/comelit-v4"
    research_dir = repo / "safety-poc/research/door/v1_5_2"
    research_src = research_dir / "comelit-v4-persistent-ring-door-diag.c"
    build_info = research_dir / "BUILD_INFO.txt"

    print("=== INPUT GATES ===")
    if not DIAG_BIN.is_file():
        raise SystemExit("DIAGNOSTIC_BINARY=ABSENT")
    if not DIAG_SRC.is_file():
        raise SystemExit("DIAGNOSTIC_SOURCE=ABSENT")
    if not native_path.is_file():
        raise SystemExit("PRODUCTION_BINARY=ABSENT")

    prod_sha = sha256(native_path)
    diag_sha = sha256(DIAG_BIN)
    print(f"PRODUCTION_SHA256={prod_sha}")
    print(f"DIAGNOSTIC_SHA256={diag_sha}")
    if prod_sha != EXPECTED_PROD_SHA:
        raise SystemExit("PRODUCTION_BINARY_GATE=FAIL")
    if diag_sha != EXPECTED_DIAG_SHA:
        raise SystemExit("DIAGNOSTIC_BINARY_GATE=FAIL")
    print("PRODUCTION_BINARY_GATE=PASS")
    print("DIAGNOSTIC_BINARY_GATE=PASS")

    print("\n=== PATCH RUNTIME ===")
    runtime = runtime_path.read_text(encoding="utf-8")
    runtime = replace_once(
        runtime,
        "        self._last_door_result: dict[str, object] | None = None\n",
        "        self._last_door_result: dict[str, object] | None = None\n"
        "        self._door_reject_diagnostic: dict[str, object] = {}\n",
        "RUNTIME_STATE_PATCH",
    )
    runtime = replace_once(
        runtime,
        "            loop = asyncio.get_running_loop()\n"
        "            future: asyncio.Future[str] = loop.create_future()\n"
        "            self._door_result_future = future\n",
        "            # Diagnostics are scoped to this one-shot Door operation.\n"
        "            # Clearing this mapping cannot cause a retry or protocol action.\n"
        "            self._door_reject_diagnostic = {}\n"
        "            loop = asyncio.get_running_loop()\n"
        "            future: asyncio.Future[str] = loop.create_future()\n"
        "            self._door_result_future = future\n",
        "RUNTIME_DIAG_RESET_PATCH",
    )
    runtime = replace_once(
        runtime,
        "            result = {\n"
        "                \"operation_id\": operation_id,\n"
        "                \"door\": door,\n"
        "                \"state\": state,\n"
        "                \"protocol_acked\": state == \"ACKED\",\n"
        "                \"write_count\": 6 if state == \"ACKED\" else None,\n"
        "                \"automatic_retry_allowed\": False,\n"
        "                \"physical_effect_asserted\": False,\n"
        "            }\n"
        "            self._last_door_result = dict(result)\n",
        "            result = {\n"
        "                \"operation_id\": operation_id,\n"
        "                \"door\": door,\n"
        "                \"state\": state,\n"
        "                \"protocol_acked\": state == \"ACKED\",\n"
        "                \"write_count\": 6 if state == \"ACKED\" else None,\n"
        "                \"automatic_retry_allowed\": False,\n"
        "                \"physical_effect_asserted\": False,\n"
        "            }\n"
        "            result.update(self._door_reject_diagnostic)\n"
        "            self._last_door_result = dict(result)\n",
        "RUNTIME_RESULT_PATCH",
    )
    runtime = replace_once(
        runtime,
        "            if line.startswith(\"V4_DOOR_RESULT=\"):\n"
        "                state = line.split(\"=\", 1)[1]\n",
        "            if line.startswith(\"V4_DOOR_REJECT_STAGE=\"):\n"
        "                self._door_reject_diagnostic[\"reject_stage\"] = (\n"
        "                    line.split(\"=\", 1)[1]\n"
        "                )\n"
        "                continue\n"
        "\n"
        "            door_numeric_diagnostics = {\n"
        "                \"V4_DOOR_REJECT_RESPONSE_WORD=\": \"reject_response_word\",\n"
        "                \"V4_DOOR_REQUESTED_CHANNEL_ID=\": \"requested_channel_id\",\n"
        "                \"V4_DOOR_RESPONSE_CHANNEL_ID=\": \"response_channel_id\",\n"
        "            }\n"
        "            numeric_diagnostic_consumed = False\n"
        "            for prefix, result_key in door_numeric_diagnostics.items():\n"
        "                if not line.startswith(prefix):\n"
        "                    continue\n"
        "                try:\n"
        "                    self._door_reject_diagnostic[result_key] = int(\n"
        "                        line.split(\"=\", 1)[1]\n"
        "                    )\n"
        "                except ValueError:\n"
        "                    _LOGGER.warning(\n"
        "                        \"Ignoring malformed Comelit Door diagnostic: %s\", line\n"
        "                    )\n"
        "                numeric_diagnostic_consumed = True\n"
        "                break\n"
        "            if numeric_diagnostic_consumed:\n"
        "                continue\n"
        "\n"
        "            if line.startswith(\"V4_DOOR_RESULT=\"):\n"
        "                state = line.split(\"=\", 1)[1]\n",
        "RUNTIME_OUTPUT_PATCH",
    )
    runtime_path.write_text(runtime, encoding="utf-8")

    print("\n=== PATCH BUTTON ===")
    button = button_path.read_text(encoding="utf-8")
    button = replace_once(
        button,
        "            \"last_protocol_acked\": result.get(\"protocol_acked\"),\n",
        "            \"last_protocol_acked\": result.get(\"protocol_acked\"),\n"
        "            \"last_reject_stage\": result.get(\"reject_stage\"),\n"
        "            \"last_reject_response_word\": result.get(\"reject_response_word\"),\n"
        "            \"last_requested_channel_id\": result.get(\"requested_channel_id\"),\n"
        "            \"last_response_channel_id\": result.get(\"response_channel_id\"),\n",
        "BUTTON_ATTRIBUTES_PATCH",
    )
    button_path.write_text(button, encoding="utf-8")

    print("\n=== PATCH MANIFEST ===")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "1.5.1":
        raise SystemExit(f"MANIFEST_VERSION_GATE=FAIL current={manifest.get('version')}")
    manifest["version"] = "1.5.2"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("MANIFEST_VERSION=1.5.2")

    print("\n=== INSTALL VERSIONED NATIVE ARTIFACT IN WORKTREE ===")
    shutil.copy2(DIAG_BIN, native_path)
    native_path.chmod(0o755)
    if sha256(native_path) != EXPECTED_DIAG_SHA:
        raise SystemExit("WORKTREE_NATIVE_SHA_GATE=FAIL")
    print("WORKTREE_NATIVE_SHA_GATE=PASS")

    research_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DIAG_SRC, research_src)
    build_info.write_text(
        "Comelit Door reject diagnostic build for HACS integration v1.5.2\n"
        f"production_base_sha256={EXPECTED_PROD_SHA}\n"
        f"diagnostic_binary_sha256={EXPECTED_DIAG_SHA}\n"
        "interpreter=/lib/ld-musl-x86_64.so.1\n"
        "automatic_retry_allowed=false\n"
        "physical_effect_asserted=false\n",
        encoding="utf-8",
    )

    print("\n=== PYTHON SYNTAX ===")
    compile(runtime_path.read_text(encoding="utf-8"), str(runtime_path), "exec")
    compile(button_path.read_text(encoding="utf-8"), str(button_path), "exec")
    print("PYTHON_SYNTAX=PASS")

    print("\n=== SAFETY CONTRACT ===")
    patched_runtime = runtime_path.read_text(encoding="utf-8")
    patched_button = button_path.read_text(encoding="utf-8")
    if "os.kill(process.pid, signal.SIGUSR1)" not in patched_runtime:
        raise SystemExit("ONE_SHOT_BOUNDARY=FAIL")
    if "automatic_retry_allowed\": False" not in patched_runtime:
        raise SystemExit("RUNTIME_NO_RETRY_CONTRACT=FAIL")
    if "\"automatic_retry_allowed\": False" not in patched_button:
        raise SystemExit("BUTTON_NO_RETRY_CONTRACT=FAIL")
    print("ONE_SHOT_BOUNDARY=PRESERVED")
    print("RUNTIME_NO_RETRY_CONTRACT=PASS")
    print("BUTTON_NO_RETRY_CONTRACT=PASS")
    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("MEDIA_ACTION_SENT=false")
    print("HACS_DOOR_DIAGNOSTIC_PREPARE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
