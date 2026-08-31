#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path


def _count(text: str, marker: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip() == marker)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _prefix_count(text: str, prefix: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith(prefix))


def _parse_operator_observation(
    path: Path | None,
    expected_operation_id: str,
) -> dict[str, str] | None:
    if path is None:
        return None
    if not path.is_file():
        raise ValueError("observation file absent")

    allowed_keys = {
        "P13_OPERATION_ID",
        "P13_PHYSICAL_OBSERVATION",
        "P13_RELAY_CLICK_OBSERVED",
        "P13_DOOR_RELEASE_OBSERVED",
        "P13_APPROX_LATENCY",
    }
    values: dict[str, str] = {}

    for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid observation line")
        key, value = line.split("=", 1)
        if key not in allowed_keys or key in values:
            raise ValueError("invalid observation key")
        values[key] = value

    required = {
        "P13_OPERATION_ID",
        "P13_PHYSICAL_OBSERVATION",
        "P13_RELAY_CLICK_OBSERVED",
        "P13_DOOR_RELEASE_OBSERVED",
        "P13_APPROX_LATENCY",
    }
    if set(values) != required:
        raise ValueError("incomplete observation")

    if values["P13_OPERATION_ID"] != expected_operation_id:
        raise ValueError("operation mismatch")

    if values["P13_PHYSICAL_OBSERVATION"] not in {
        "OPENED",
        "NOT_OPENED",
        "UNAVAILABLE",
    }:
        raise ValueError("invalid physical observation")

    for key in (
        "P13_RELAY_CLICK_OBSERVED",
        "P13_DOOR_RELEASE_OBSERVED",
    ):
        if values[key] not in {"true", "false", "unknown"}:
            raise ValueError("invalid boolean observation")

    latency = values["P13_APPROX_LATENCY"]
    if latency != "unknown" and re.fullmatch(
        r"[0-9]+(?:\.[0-9]+)?(?:ms|s)",
        latency,
    ) is None:
        raise ValueError("invalid latency")

    return values


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect public-safe, read-only evidence for one completed P13 operation"
    )
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--db", default="/root/comelit-p13-run/p13-one-shot.sqlite3")
    parser.add_argument("--audit", default="/root/comelit-p13-audit/audit.jsonl")
    parser.add_argument("--live-log", default="/root/comelit-p13-run/p13-live-run.log")
    parser.add_argument("--physical-log-dir", default="/root/comelit-p13-run")
    parser.add_argument(
        "--observed-log",
        type=Path,
        default=Path("/root/comelit-p13-run/hermes-observed-acceptance-v1.log"),
    )
    parser.add_argument(
        "--observed-state",
        type=Path,
        default=Path("/root/comelit-p13-run/hermes-observed-acceptance-v1.state"),
    )
    parser.add_argument(
        "--operator-observation",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    operation_id = args.operation_id
    db = Path(args.db)
    audit = Path(args.audit)
    live_log = Path(args.live_log)
    physical_log_dir = Path(args.physical_log_dir)
    observed_log = args.observed_log
    observed_state = args.observed_state
    operator_observation = args.operator_observation

    print("P13_POST_ATTEMPT_EVIDENCE_START=true")
    print(f"P13_OPERATION_ID={operation_id}")
    print("P13_COLLECTOR_NETWORK_ACTION=false")
    print("P13_COLLECTOR_PHYSICAL_ACTION=false")

    if not db.is_file():
        print("P13_DB_PRESENT=false")
        return 2

    con = _connect_readonly(db)
    con.row_factory = sqlite3.Row
    try:
        op = con.execute(
            "SELECT state FROM operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if op is None:
            print("P13_OPERATION_PRESENT=false")
            return 3
        print("P13_OPERATION_PRESENT=true")
        print(f"P13_STATE={op['state']}")

        rows = con.execute(
            "SELECT from_state,to_state FROM events WHERE operation_id=? ORDER BY id",
            (operation_id,),
        ).fetchall()
    finally:
        con.close()

    transitions: dict[tuple[str, str], int] = {}
    for row in rows:
        src = row["from_state"] if row["from_state"] is not None else "NONE"
        dst = row["to_state"]
        transitions[(src, dst)] = transitions.get((src, dst), 0) + 1

    for src, dst in (
        ("NONE", "PREPARED"),
        ("PREPARED", "SEND_ARMED"),
        ("SEND_ARMED", "SENT"),
        ("SENT", "UNKNOWN_OUTCOME"),
        ("SENT", "ACKED"),
        ("PREPARED", "FAILED_SAFE"),
        ("SEND_ARMED", "UNKNOWN_OUTCOME"),
    ):
        print(f"P13_EVENT_{src}_TO_{dst}_COUNT={transitions.get((src, dst), 0)}")

    attempt_count = 0
    outcome_count = 0
    attempt_number_one = True
    if audit.is_file():
        for line in audit.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("operation_id") != operation_id:
                continue
            if item.get("event_type") == "transport_attempt":
                attempt_count += 1
                attempt_number_one = attempt_number_one and item.get("attempt_number") == 1
            elif item.get("event_type") == "transport_outcome":
                outcome_count += 1
                attempt_number_one = attempt_number_one and item.get("attempt_number") == 1
    print(f"P13_AUDIT_TRANSPORT_ATTEMPT_COUNT={attempt_count}")
    print(f"P13_AUDIT_TRANSPORT_OUTCOME_COUNT={outcome_count}")
    print(f"P13_AUDIT_ATTEMPT_NUMBER_FIXED_1={'true' if attempt_number_one else 'false'}")

    matching_physical_logs: list[Path] = []
    if physical_log_dir.is_dir():
        for path in sorted(physical_log_dir.glob("p13-physical-*.log")):
            text = _read(path)
            if operation_id in text:
                matching_physical_logs.append(path)

    observed_text = _read(observed_log)
    observed_log_matches = operation_id in observed_text
    if observed_log_matches and observed_log not in matching_physical_logs:
        matching_physical_logs.append(observed_log)

    print(f"P13_PHYSICAL_LOG_MATCH_COUNT={len(matching_physical_logs)}")
    print(
        "P13_HERMES_OBSERVED_LOG_OPERATION_MATCH="
        + ("true" if observed_log_matches else "false")
    )

    gate_state = _read(observed_state).strip()
    gate_consumed = gate_state == "CONSUMED_BEFORE_LIVE_ENTRYPOINT"
    print(
        "P13_HERMES_OBSERVED_GATE_TERMINAL_CONSUMED="
        + ("true" if gate_consumed else "false")
    )
    print("P13_HERMES_OBSERVED_RESEND_ALLOWED=false" if gate_consumed
          else "P13_HERMES_OBSERVED_RESEND_ALLOWED=indeterminate")

    physical_text = "\n".join(_read(path) for path in matching_physical_logs)
    print(f"P13_HERMES_TRIGGER_ACCEPTED_COUNT={_count(physical_text, 'P13_HERMES_TRIGGER=ACCEPTED')}")
    print(f"P13_RUNNER_APPROVAL_GRANTED_COUNT={_count(physical_text, 'P13_ONE_SHOT_APPROVAL=GRANTED')}")
    print(f"P13_RUNNER_PREFLIGHT_PASS_COUNT={_count(physical_text, 'P13_ONE_SHOT_PREFLIGHT=PASS')}")
    print(f"P13_RUNNER_COMPLETE_COUNT={_count(physical_text, 'P13_ONE_SHOT_LAST_STEP=COMPLETE')}")

    live = _read(live_log)
    print(f"P13_SIGNALING_HOLDER_BIND_PASS_COUNT={_count(live, 'P13_SIGNALING_HOLDER_BIND=PASS')}")
    print(f"P13_SIGNALING_WRAPPER_READY_COUNT={_count(live, 'P13_SIGNALING_WRAPPER_READY=true')}")
    print(f"P13_CTPP_OPENED_MARKER_COUNT={_count(live, 'P13_CTPP_OPEN_OUTCOME=OPENED')}")
    print(f"P13_DOOR_WRITE_COUNT_6_MARKER_COUNT={_count(live, 'P13_DOOR_WRITE_COUNT=6')}")
    print(f"P13_CTPP_CLOSE_PASS_MARKER_COUNT={_count(live, 'P13_CTPP_CLOSE=PASS')}")
    print(f"P13_TEARDOWN_PASS_MARKER_COUNT={_count(live, 'P13_TEARDOWN=PASS')}")
    print(
        "P13_CTPP_RX_EVIDENCE_COUNT="
        f"{_prefix_count(live, 'P13_CTPP_RX_EVIDENCE ')}"
    )
    print(
        "P13_DOOR_RESPONSE_SEEN_COUNT="
        f"{_count(live, 'P13_DOOR_RESPONSE_SEEN=true')}"
    )

    terminal = op["state"] in {"ACKED", "FAILED_SAFE", "UNKNOWN_OUTCOME"}
    one_attempt = attempt_count == 1 and attempt_number_one
    print(f"P13_OPERATION_TERMINAL={'true' if terminal else 'false'}")
    print(f"P13_ONE_AUDITED_TRANSPORT_ATTEMPT={'true' if one_attempt else 'false'}")
    print("P13_DUPLICATE_TRANSMISSION_EVIDENCE=NOT_OBSERVED" if one_attempt else "P13_DUPLICATE_TRANSMISSION_EVIDENCE=INDETERMINATE")
    print("P13_PHYSICAL_EFFECT_ASSERTED=false")

    try:
        observation = _parse_operator_observation(
            operator_observation,
            operation_id,
        )
    except (OSError, UnicodeError, ValueError):
        print("P13_OPERATOR_OBSERVATION_VALID=false")
        return 4

    if observation is None:
        print("P13_OPERATOR_OBSERVATION_PRESENT=false")
        print("P13_OPERATOR_OBSERVATION_VALID=true")
        print("P13_PHYSICAL_OBSERVATION=UNAVAILABLE")
        print("P13_RELAY_CLICK_OBSERVED=unknown")
        print("P13_DOOR_RELEASE_OBSERVED=unknown")
        print("P13_APPROX_LATENCY=unknown")
        print("P13_OBSERVED_PHYSICAL_ACCEPTANCE=UNAVAILABLE")
    else:
        print("P13_OPERATOR_OBSERVATION_PRESENT=true")
        print("P13_OPERATOR_OBSERVATION_VALID=true")
        print("P13_OPERATOR_OBSERVATION_OPERATION_MATCH=true")

        physical = observation["P13_PHYSICAL_OBSERVATION"]
        print(f"P13_PHYSICAL_OBSERVATION={physical}")
        print(
            "P13_RELAY_CLICK_OBSERVED="
            + observation["P13_RELAY_CLICK_OBSERVED"]
        )
        print(
            "P13_DOOR_RELEASE_OBSERVED="
            + observation["P13_DOOR_RELEASE_OBSERVED"]
        )
        print(
            "P13_APPROX_LATENCY="
            + observation["P13_APPROX_LATENCY"]
        )

        acceptance = {
            "OPENED": "PASS",
            "NOT_OPENED": "FAIL",
            "UNAVAILABLE": "UNAVAILABLE",
        }[physical]
        print(f"P13_OBSERVED_PHYSICAL_ACCEPTANCE={acceptance}")

    print("P13_POST_ATTEMPT_EVIDENCE_COMPLETE=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
