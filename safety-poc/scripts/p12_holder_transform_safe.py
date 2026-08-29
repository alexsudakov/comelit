#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BASE = SCRIPT_DIR / "p12_holder_transform.py"

spec = importlib.util.spec_from_file_location("p12_holder_transform_base", BASE)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def transform(source: str, ucfg_body: bytes) -> str:
    original_helpers = module.p12_helpers

    def helpers_with_distinct_final_timer() -> str:
        text = original_helpers()
        old = """            g_timeout_add(\n                250,\n                pseudotcp_success_quit_cb,\n                NULL\n            );"""
        new = """            g_timeout_add (\n                250,\n                pseudotcp_success_quit_cb,\n                NULL\n            );"""
        if text.count(old) != 1:
            raise RuntimeError("expected one final P12 success timer in helper block")
        return text.replace(old, new, 1)

    module.p12_helpers = helpers_with_distinct_final_timer
    try:
        transformed = module.transform(source, ucfg_body)
    finally:
        module.p12_helpers = original_helpers

    if transformed.count("g_timeout_add (\n                250,\n                pseudotcp_success_quit_cb") != 1:
        raise RuntimeError("final P12 success timer is not preserved exactly once")

    if "g_timeout_add(\n        250,\n        pseudotcp_success_quit_cb" in transformed:
        raise RuntimeError("premature baseline UAUT success timer remains")

    if transformed.count("if (!p12_begin_auth())") != 1:
        raise RuntimeError("UAUT-open handoff to P12 auth is not unique")

    return transformed


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe entry point for P12 holder transformation")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    templates = json.loads(args.templates.read_text(encoding="utf-8"))
    ucfg_body = bytes.fromhex(templates["ucfg_body_hex"])
    source = args.source.read_text(encoding="utf-8")
    transformed = transform(source, ucfg_body)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(transformed, encoding="utf-8")

    print("P12_HOLDER_TRANSFORM_SAFE=PASS")
    print("P12_PREMATURE_UAUT_SUCCESS_TIMER=false")
    print("P12_FINAL_SUCCESS_TIMER_COUNT=1")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
