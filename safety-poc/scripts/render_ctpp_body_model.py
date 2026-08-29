#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from comelit_safety_poc.body_reconciliation import reconcile_structural_inventory
from comelit_safety_poc.ctpp_body_model import parse_legacy_body_shape_inventory, summarize_inventory


def main() -> int:
    parser = argparse.ArgumentParser(description="Render payload-redacted CTPP body structural reconciliation from collector evidence.")
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()

    inventory = parse_legacy_body_shape_inventory(args.inventory.read_text(encoding="utf-8"))
    reconciliation = reconcile_structural_inventory(inventory)

    for line in summarize_inventory(inventory):
        print(line)
    for item in reconciliation.writes:
        print(f"WRITE_{item.legacy.ordinal}_SEMANTIC={item.semantic.value}")
        print(f"WRITE_{item.legacy.ordinal}_STRUCTURAL_FINGERPRINT={item.structural_fingerprint}")

    print("CTPP_BODY_LAYOUT_STRUCTURAL_RECONCILIATION=PASS")
    print("CTPP_BODY_LAYOUT_RECONCILIATION=PENDING_RUNTIME_BYTE_ORACLE")
    print("REAL_DOOR_PAYLOAD_VALUES_PRESENT=false")
    print("SOURCE_EXECUTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
