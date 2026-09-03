#!/usr/bin/env python3

import argparse
import os
import re
import secrets
from pathlib import Path


CAND_RE = re.compile(
    r"^a=candidate:"
    r"(\S+)\s+"
    r"(\d+)\s+"
    r"(UDP|TCP)\s+"
    r"(\d+)\s+"
    r"(\S+)\s+"
    r"(\d+)\s+"
    r"typ\s+"
    r"(\S+)"
    r"(?:\s+.*)?$",
    re.IGNORECASE,
)


def fail(msg):
    print(f"COMELIT_SDP_ERROR={msg}")
    raise SystemExit(2)


def load_lines(path):
    data = Path(path).read_bytes()

    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        fail("RAW_SDP_NOT_ASCII")

    return [
        line.strip()
        for line in re.split(r"\r\n|\n|\r", text)
        if line.strip()
    ]


def exactly_one(lines, prefix, name):
    values = [
        line[len(prefix):]
        for line in lines
        if line.startswith(prefix)
    ]

    if len(values) != 1:
        fail(f"{name}_COUNT_{len(values)}")

    return values[0]


def parse_raw(path):
    lines = load_lines(path)

    mlines = [
        line
        for line in lines
        if line.startswith("m=")
    ]

    if len(mlines) != 1:
        fail(f"RAW_MLINE_COUNT_{len(mlines)}")

    mp = mlines[0][2:].split()

    if len(mp) < 3:
        fail("RAW_MLINE_INVALID")

    try:
        port = int(mp[1])
    except ValueError:
        fail("RAW_PORT_INVALID")

    if not (1 <= port <= 65535):
        fail("RAW_PORT_RANGE")

    c_ips = []

    for line in lines:
        if line.startswith("c=IN IP4 "):
            c_ips.append(
                line[len("c=IN IP4 "):].strip()
            )

    usable_ips = [
        ip
        for ip in c_ips
        if ip and ip != "0.0.0.0"
    ]

    if not usable_ips:
        fail("RAW_DEFAULT_IP_MISSING")

    default_ip = usable_ips[0]

    ufrag = exactly_one(
        lines,
        "a=ice-ufrag:",
        "RAW_UFRAG",
    )

    pwd = exactly_one(
        lines,
        "a=ice-pwd:",
        "RAW_PWD",
    )

    candidates = [
        line
        for line in lines
        if line.startswith("a=candidate:")
    ]

    if not candidates:
        fail("RAW_CANDIDATES_EMPTY")

    types = []

    for line in candidates:
        m = CAND_RE.match(line)

        if not m:
            fail("RAW_CANDIDATE_INVALID")

        component = int(m.group(2))
        transport = m.group(3).upper()
        cand_type = m.group(7).lower()

        if component != 1:
            fail(
                f"UNEXPECTED_COMPONENT_{component}"
            )

        if transport != "UDP":
            fail(
                f"UNEXPECTED_TRANSPORT_{transport}"
            )

        types.append(cand_type)

    if "host" not in types:
        fail("HOST_CANDIDATE_MISSING")

    if "srflx" not in types:
        fail("SRFLX_CANDIDATE_MISSING")

    return {
        "raw_lines": lines,
        "port": port,
        "default_ip": default_ip,
        "ufrag": ufrag,
        "pwd": pwd,
        "candidates": candidates,
        "types": types,
        "raw_mline": mlines[0],
    }


def build(parsed):
    # Android libc rand() is non-negative.
    # Exact numeric value has no protocol identity
    # significance; native prints one value twice.
    origin = secrets.randbelow(
        0x7fffffff
    ) + 1

    lines = [
        "v=0",
        (
            f"o=- {origin} {origin} "
            "IN IP4 0.0.0.0"
        ),
        "s=ice",
        "t=0 0",
        "a=nego-wait:0",
        "a=comelit-legacy-session:TCP",
        "a=comelit-session-id:MUX",
        "a=comelit-nego-aggressive:true",
        "c=IN IP4 0.0.0.0",
        (
            f"m=audio {parsed['port']} "
            "RTP/SAVPF 0 8"
        ),
        "b=RS:0",
        "b=RR:0",
        (
            "c=IN IP4 "
            f"{parsed['default_ip']}"
        ),
        "a=sendrecv",
    ]

    lines.extend(
        parsed["candidates"]
    )

    lines.extend(
        [
            "a=ice-role:a",
            (
                "a=ice-ufrag:"
                f"{parsed['ufrag']}"
            ),
            (
                "a=ice-pwd:"
                f"{parsed['pwd']}"
            ),
        ]
    )

    return (
        "\r\n".join(lines)
        + "\r\n"
    ).encode("ascii")


def validate(parsed, data):
    if not data.endswith(b"\r\n"):
        fail("NO_FINAL_CRLF")

    if data.count(b"\n") != data.count(b"\r\n"):
        fail("NON_CRLF_LINE_ENDINGS")

    text = data.decode("ascii")

    lines = [
        line
        for line in text.split("\r\n")
        if line
    ]

    expected_prefix = [
        "v=0",
        None,
        "s=ice",
        "t=0 0",
        "a=nego-wait:0",
        "a=comelit-legacy-session:TCP",
        "a=comelit-session-id:MUX",
        "a=comelit-nego-aggressive:true",
        "c=IN IP4 0.0.0.0",
        (
            f"m=audio {parsed['port']} "
            "RTP/SAVPF 0 8"
        ),
        "b=RS:0",
        "b=RR:0",
        (
            "c=IN IP4 "
            f"{parsed['default_ip']}"
        ),
        "a=sendrecv",
    ]

    if len(lines) < len(expected_prefix):
        fail("OUTPUT_TOO_SHORT")

    for i, expected in enumerate(
        expected_prefix
    ):
        if expected is None:
            if not re.fullmatch(
                r"o=- (\d+) \1 "
                r"IN IP4 0\.0\.0\.0",
                lines[i],
            ):
                fail("ORIGIN_INVALID")
        elif lines[i] != expected:
            fail(
                f"PREFIX_MISMATCH_LINE_{i+1}"
            )

    if any(
        line.startswith("m=application ")
        for line in lines
    ):
        fail("APPLICATION_MLINE_PRESENT")

    out_candidates = [
        line
        for line in lines
        if line.startswith("a=candidate:")
    ]

    if out_candidates != parsed["candidates"]:
        fail("CANDIDATES_CHANGED")

    if (
        "a=ice-ufrag:"
        + parsed["ufrag"]
    ) not in lines:
        fail("UFRAG_CHANGED")

    if (
        "a=ice-pwd:"
        + parsed["pwd"]
    ) not in lines:
        fail("PWD_CHANGED")

    if lines[-3] != "a=ice-role:a":
        fail("ROLE_POSITION")

    if not lines[-2].startswith(
        "a=ice-ufrag:"
    ):
        fail("UFRAG_POSITION")

    if not lines[-1].startswith(
        "a=ice-pwd:"
    ):
        fail("PWD_POSITION")


def write_secure(path, data):
    dst = Path(path)

    dst.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = dst.with_name(
        dst.name + ".tmp"
    )

    old_umask = os.umask(0o077)

    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        os.chmod(tmp, 0o600)
        os.replace(tmp, dst)

    finally:
        os.umask(old_umask)

        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--input",
        required=True,
    )

    ap.add_argument(
        "--output",
        required=True,
    )

    args = ap.parse_args()

    parsed = parse_raw(
        args.input
    )

    data = build(parsed)

    validate(
        parsed,
        data,
    )

    write_secure(
        args.output,
        data,
    )

    host_count = sum(
        t == "host"
        for t in parsed["types"]
    )

    srflx_count = sum(
        t == "srflx"
        for t in parsed["types"]
    )

    print("COMELIT_SDP_BUILD=PASS")
    print("COMELIT_SDP_VALIDATE=PASS")
    print(
        "RAW_MLINE="
        + parsed["raw_mline"]
    )
    print(
        "COMELIT_MEDIA=audio/RTP-SAVPF"
    )
    print(
        "DEFAULT_IP="
        + parsed["default_ip"]
    )
    print(
        "DEFAULT_PORT="
        + str(parsed["port"])
    )
    print(
        "CANDIDATE_COUNT="
        + str(
            len(parsed["candidates"])
        )
    )
    print(
        "HOST_COUNT="
        + str(host_count)
    )
    print(
        "SRFLX_COUNT="
        + str(srflx_count)
    )
    print("ICE_ROLE=CONTROLLED(a)")
    print("SESSION_ID=2")
    print("MUX=true")
    print("NEGO_WAIT=0")
    print("NEGO_AGGRESSIVE=true")
    print(
        "ICE_UFRAG_LEN="
        + str(len(parsed["ufrag"]))
    )
    print(
        "ICE_PWD_LEN="
        + str(len(parsed["pwd"]))
    )


if __name__ == "__main__":
    main()
