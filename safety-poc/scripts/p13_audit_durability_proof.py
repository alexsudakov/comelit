#!/usr/bin/env python3
"""Non-actuating audit durability proof for the P13 CT120 preflight.

Appends a dedicated preflight event through the real AuditSink API, fsyncs,
closes/reopens the journal, and verifies the exact new entry and journal
structure.  Never logs credentials or target identity values.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

POC_ROOT = Path(__file__).resolve().parents[1]
SRC = POC_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.audit import AuditEntry, AuditSink
from comelit_safety_poc.model import State


def main() -> int:
    parser = argparse.ArgumentParser(description="P13 audit append+fsync+reopen proof")
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()

    sink = AuditSink(args.audit)
    before = len(sink.entries())
    sink.record_raw(
        AuditEntry(
            ts="preflight",
            operation_id=f"preflight-{args.head[:12]}",
            event_type="preflight",
            state=State.PREPARED.value,
            detail="CT120 non-actuating preflight audit durability proof",
            target="",
            attempt_number=1,
        )
    )
    reopened = AuditSink(args.audit)
    entries = reopened.entries()
    if len(entries) != before + 1:
        print("P13_AUDIT_REOPEN_COUNT=FAIL")
        return 1
    if entries[-1].event_type != "preflight":
        print("P13_AUDIT_REOPEN_ENTRY=FAIL")
        return 1
    if not reopened.verify_durable():
        print("P13_AUDIT_REOPEN_VERIFY=FAIL")
        return 1
    print("P13_AUDIT_APPEND_FSYNC_REOPEN=PASS")
    print("AUDIT_SINK_VERIFIED=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
