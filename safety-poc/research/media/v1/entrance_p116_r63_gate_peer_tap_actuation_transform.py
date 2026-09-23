#!/usr/bin/env python3
"""P116/R63: promote the Gate peer/TAP actuation profile.

The R63 overlay composes the proven R58 production source and adds a second
Door target to the existing one-shot persistent-CTPP path.  It does not replay
raw PCAP payloads.  The Gate five-write body set is derived mechanically from
the already-live-proven Entrance peer/TAP bodies by replacing only the
peer-address field (00000643 -> 00000610); output-index=1 and all non-target
bytes remain byte-identical.

Gate target provenance:
* target 00000610: owner PCAPdroid capture, SHA256
  5645b4b0607f746b057ce6b6603f8d6165f20167894927aca5a7c8b4b744e636;
* action=peer / output-index=1: captured UCFG/address-book configuration;
* five-opcode peer/TAP layout: generic parameterised implementation in
  nicolas-fricke/ha-component-comelit-intercom PR #12 and the pinned legacy
  IconaBridgeClient.open_door model;
* persistent CTPP reuse, one-shot/no-retry and conservative UNKNOWN_OUTCOME:
  existing production Entrance contract.

Python writes an exact bounded target token to /run/comelit-p2p/door-target
before the existing SIGUSR1 boundary.  Native consumes and unlinks it before
any Door write. Missing or malformed target data fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re

import entrance_p116_r58_attached_media_stop_cleanup_corrective as r58


BEGIN = "/* R63_GATE_PEER_TAP_BEGIN */"
END = "/* R63_GATE_PEER_TAP_END */"

ENTRANCE_ADDR = b"00000643"
GATE_ADDR = b"00000610"
EXPECTED_OCCURRENCES = (1, 1, 2, 1, 1)

_ARRAY_ANCHOR = "static const guint v4_door_write_count = 5;"

_STATE_BLOCK = r'''/* R63_GATE_PEER_TAP_BEGIN */
#define V4_DOOR_TARGET_FILE RUN_DIR "/door-target"

typedef enum {
    V4_DOOR_TARGET_NONE = 0,
    V4_DOOR_TARGET_ENTRANCE,
    V4_DOOR_TARGET_GATE
} V4DoorTarget;

static V4DoorTarget v4_door_target = V4_DOOR_TARGET_NONE;

static const char *
v4_door_target_name(V4DoorTarget target)
{
    switch (target) {
    case V4_DOOR_TARGET_ENTRANCE: return "entrance";
    case V4_DOOR_TARGET_GATE: return "gate";
    case V4_DOOR_TARGET_NONE:
    default:
        return "none";
    }
}

static V4DoorTarget
v4_door_read_target(void)
{
    gchar *contents = NULL;
    gsize length = 0;
    GError *error = NULL;
    V4DoorTarget target = V4_DOOR_TARGET_NONE;

    if (!g_file_get_contents(V4_DOOR_TARGET_FILE, &contents, &length, &error)) {
        if (error)
            g_error_free(error);
        return V4_DOOR_TARGET_NONE;
    }

    gchar *value = g_strstrip(contents);
    if (g_strcmp0(value, "entrance") == 0)
        target = V4_DOOR_TARGET_ENTRANCE;
    else if (g_strcmp0(value, "gate") == 0)
        target = V4_DOOR_TARGET_GATE;

    if (contents && length > 0)
        memset(contents, 0, length);
    g_free(contents);
    (void)g_unlink(V4_DOOR_TARGET_FILE);
    return target;
}
/* R63_GATE_PEER_TAP_END */'''

_RESET_ANCHOR = """    v4_door_write_index = 0;
    v4_door_writes_sent = 0;
    v4_door_deadline_us = 0;
    v4_door_send_started = FALSE;
}"""
_RESET_REPLACEMENT = """    v4_door_write_index = 0;
    v4_door_writes_sent = 0;
    v4_door_deadline_us = 0;
    v4_door_send_started = FALSE;
    v4_door_target = V4_DOOR_TARGET_NONE;
}"""

_SWITCH_TAIL_ANCHOR = """        default:
            return FALSE;
    }

    /*
     * The listener-owned CTPP channel is deliberately reused here."""
_SWITCH_TAIL_REPLACEMENT = """        default:
            return FALSE;
    }

    if (v4_door_target == V4_DOOR_TARGET_GATE) {
        switch (index) {
            case 1:
                body = v4_gate_operation_body_1;
                body_len = v4_door_operation_body_len[0];
                break;
            case 2:
                body = v4_gate_operation_body_2;
                body_len = v4_door_operation_body_len[1];
                break;
            case 3:
                body = v4_gate_operation_body_3;
                body_len = v4_door_operation_body_len[2];
                break;
            case 4:
                body = v4_gate_operation_body_4;
                body_len = v4_door_operation_body_len[3];
                break;
            case 5:
                body = v4_gate_operation_body_5;
                body_len = v4_door_operation_body_len[4];
                break;
            default:
                return FALSE;
        }
    } else if (v4_door_target != V4_DOOR_TARGET_ENTRANCE) {
        return FALSE;
    }

    /*
     * The listener-owned CTPP channel is deliberately reused here."""

_TARGET_READ_ANCHOR = """    v4_door_signal_pending = 0;

    if (!v4_listener_ready ||"""
_TARGET_READ_REPLACEMENT = """    v4_door_signal_pending = 0;

    v4_door_target = v4_door_read_target();
    if (v4_door_target == V4_DOOR_TARGET_NONE) {
        printf("V4_DOOR_TARGET_VALID=false\\n");
        v4_door_emit_result("FAILED_SAFE");
        v4_door_reset();
        return G_SOURCE_CONTINUE;
    }
    printf("V4_DOOR_TARGET_VALID=true\\n");

    if (!v4_listener_ready ||"""

_REJECT_ANCHOR = """        printf("V4_DOOR_RESULT=REJECTED_NOT_READY\\n");
        fflush(stdout);
        return G_SOURCE_CONTINUE;
    }

    printf("V4_DOOR_COMMAND_ACCEPTED=true\\n");
    printf("V4_DOOR_TARGET=entrance\\n");"""
_REJECT_REPLACEMENT = """        printf("V4_DOOR_RESULT=REJECTED_NOT_READY\\n");
        fflush(stdout);
        v4_door_reset();
        return G_SOURCE_CONTINUE;
    }

    printf("V4_DOOR_COMMAND_ACCEPTED=true\\n");
    printf("V4_DOOR_TARGET=%s\\n", v4_door_target_name(v4_door_target));"""


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"R63_{label}_ANCHOR_GATE=FAIL count={count}")
    return text.replace(old, new, 1)


def _parse_array(text: str, name: str) -> bytes:
    match = re.search(
        rf"static const guint8 {re.escape(name)}\[\] = \{{(?P<body>.*?)\}};",
        text,
        re.S,
    )
    if not match:
        raise RuntimeError(f"R63_SOURCE_ARRAY_GATE=FAIL name={name}")
    return bytes(
        int(item, 16)
        for item in re.findall(r"0x([0-9a-fA-F]{2})", match.group("body"))
    )


def _render_array(name: str, data: bytes) -> str:
    rows = []
    for start in range(0, len(data), 12):
        chunk = data[start : start + 12]
        rows.append("    " + ", ".join(f"0x{value:02x}" for value in chunk) + ",")
    return (
        f"static const guint8 {name}[] = {{\n"
        + "\n".join(rows)
        + "\n};"
    )


def _gate_arrays(candidate: str) -> str:
    rendered: list[str] = []
    for index, expected in enumerate(EXPECTED_OCCURRENCES, 1):
        entrance = _parse_array(candidate, f"v4_door_operation_body_{index}")
        if entrance.count(ENTRANCE_ADDR) != expected:
            raise RuntimeError(
                f"R63_ENTRANCE_ADDRESS_PROVENANCE_GATE=FAIL body={index}"
            )
        if GATE_ADDR in entrance:
            raise RuntimeError(
                f"R63_GATE_ADDRESS_ALREADY_PRESENT_GATE=FAIL body={index}"
            )
        gate = entrance.replace(ENTRANCE_ADDR, GATE_ADDR)
        if gate.count(GATE_ADDR) != expected:
            raise RuntimeError(f"R63_GATE_DERIVATION_GATE=FAIL body={index}")
        if len(gate) != len(entrance):
            raise RuntimeError(f"R63_LENGTH_PRESERVATION_GATE=FAIL body={index}")
        # dst is apt-base + output-index=1 in all five production bodies.
        if b"000401171" not in gate:
            raise RuntimeError(f"R63_OUTPUT_INDEX_GATE=FAIL body={index}")
        rendered.append(_render_array(f"v4_gate_operation_body_{index}", gate))
    return "\n\n".join(rendered)


def transform(source: str) -> str:
    if BEGIN in source:
        raise RuntimeError("R63_REAPPLY_GATE=FAIL")

    candidate = r58.transform(source)
    gate_arrays = _gate_arrays(candidate)

    candidate = _replace_once(
        candidate,
        _ARRAY_ANCHOR,
        _ARRAY_ANCHOR + "\n\n" + gate_arrays + "\n\n" + _STATE_BLOCK,
        "ARRAYS",
    )
    candidate = _replace_once(
        candidate, _RESET_ANCHOR, _RESET_REPLACEMENT, "RESET"
    )
    candidate = _replace_once(
        candidate,
        _SWITCH_TAIL_ANCHOR,
        _SWITCH_TAIL_REPLACEMENT,
        "QUEUE_TARGET",
    )
    candidate = _replace_once(
        candidate,
        _TARGET_READ_ANCHOR,
        _TARGET_READ_REPLACEMENT,
        "TARGET_READ",
    )
    candidate = _replace_once(
        candidate,
        _REJECT_ANCHOR,
        _REJECT_REPLACEMENT,
        "TARGET_MARKER",
    )

    if candidate.count(BEGIN) != 1 or candidate.count(END) != 1:
        raise RuntimeError("R63_MARKER_GATE=FAIL")
    if candidate.count("signal(SIGUSR1, v4_door_signal_handler);") != 1:
        raise RuntimeError("R63_SIGUSR1_GATE=FAIL")
    if candidate.count("V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false") < 2:
        raise RuntimeError("R63_NO_RETRY_GATE=FAIL")
    if candidate.count("V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false") < 2:
        raise RuntimeError("R63_NO_PHYSICAL_ASSERT_GATE=FAIL")
    if "V4_DOOR_TARGET=%s" not in candidate:
        raise RuntimeError("R63_DYNAMIC_TARGET_MARKER_GATE=FAIL")
    if "V4_DOOR_TARGET=entrance" in candidate:
        raise RuntimeError("R63_HARDCODED_TARGET_GATE=FAIL")

    # Entrance bytes must be completely unchanged by R63.
    r58_candidate = r58.transform(source)
    for index in range(1, 6):
        before = _parse_array(r58_candidate, f"v4_door_operation_body_{index}")
        after = _parse_array(candidate, f"v4_door_operation_body_{index}")
        if before != after:
            raise RuntimeError(
                f"R63_ENTRANCE_BYTE_IDENTITY_GATE=FAIL body={index}"
            )
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sha256", action="store_true")
    args = parser.parse_args(argv)

    safety_poc_root = Path(__file__).resolve().parents[3]
    source_path = args.source or (
        safety_poc_root
        / "research"
        / "door"
        / "v1_5_7"
        / "comelit-v4-persistent-ctpp-door.c"
    )
    candidate = transform(source_path.read_text(encoding="utf-8"))

    if args.sha256:
        print(hashlib.sha256(candidate.encode("utf-8")).hexdigest())
        return 0
    if args.output is None:
        parser.error("--output is required unless --sha256 is used")

    args.output.write_text(candidate, encoding="utf-8")
    print("R63_GATE_PEER_TAP_TRANSFORM=PASS")
    print(
        "R63_GENERATED_SOURCE_SHA256="
        + hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    )
    print("R63_GATE_TARGET=00000610")
    print("R63_GATE_OUTPUT_INDEX=1")
    print("R63_GATE_WRITE_COUNT=5")
    print("R63_ENTRANCE_BYTES_UNCHANGED=true")
    print("R63_AUTOMATIC_RETRY=false")
    print("R63_PHYSICAL_EFFECT_ASSERTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
