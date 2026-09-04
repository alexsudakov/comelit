from __future__ import annotations

import re
import secrets

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


class ComelitSdpError(ValueError):
    """Local libnice SDP cannot be transformed to Comelit's wire format."""


def _fail(message: str) -> None:
    raise ComelitSdpError(message)


def _load_lines(data: bytes) -> list[str]:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ComelitSdpError("RAW_SDP_NOT_ASCII") from exc

    return [
        line.strip()
        for line in re.split(r"\r\n|\n|\r", text)
        if line.strip()
    ]


def _exactly_one(lines: list[str], prefix: str, name: str) -> str:
    values = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
    if len(values) != 1:
        _fail(f"{name}_COUNT_{len(values)}")
    return values[0]


def _parse_raw(data: bytes) -> dict[str, object]:
    lines = _load_lines(data)
    mlines = [line for line in lines if line.startswith("m=")]
    if len(mlines) != 1:
        _fail(f"RAW_MLINE_COUNT_{len(mlines)}")

    mp = mlines[0][2:].split()
    if len(mp) < 3:
        _fail("RAW_MLINE_INVALID")

    try:
        port = int(mp[1])
    except ValueError as exc:
        raise ComelitSdpError("RAW_PORT_INVALID") from exc
    if not 1 <= port <= 65535:
        _fail("RAW_PORT_RANGE")

    c_ips = [
        line[len("c=IN IP4 ") :].strip()
        for line in lines
        if line.startswith("c=IN IP4 ")
    ]
    usable_ips = [ip for ip in c_ips if ip and ip != "0.0.0.0"]
    if not usable_ips:
        _fail("RAW_DEFAULT_IP_MISSING")

    ufrag = _exactly_one(lines, "a=ice-ufrag:", "RAW_UFRAG")
    pwd = _exactly_one(lines, "a=ice-pwd:", "RAW_PWD")
    candidates = [line for line in lines if line.startswith("a=candidate:")]
    if not candidates:
        _fail("RAW_CANDIDATES_EMPTY")

    types: list[str] = []
    for line in candidates:
        match = CAND_RE.match(line)
        if not match:
            _fail("RAW_CANDIDATE_INVALID")
        component = int(match.group(2))
        transport = match.group(3).upper()
        cand_type = match.group(7).lower()
        if component != 1:
            _fail(f"UNEXPECTED_COMPONENT_{component}")
        if transport != "UDP":
            _fail(f"UNEXPECTED_TRANSPORT_{transport}")
        types.append(cand_type)

    if "host" not in types:
        _fail("HOST_CANDIDATE_MISSING")
    if "srflx" not in types:
        _fail("SRFLX_CANDIDATE_MISSING")

    return {
        "port": port,
        "default_ip": usable_ips[0],
        "ufrag": ufrag,
        "pwd": pwd,
        "candidates": candidates,
        "types": types,
    }


def _build(parsed: dict[str, object]) -> bytes:
    origin = secrets.randbelow(0x7FFFFFFF) + 1
    port = int(parsed["port"])
    default_ip = str(parsed["default_ip"])
    candidates = list(parsed["candidates"])
    ufrag = str(parsed["ufrag"])
    pwd = str(parsed["pwd"])

    lines = [
        "v=0",
        f"o=- {origin} {origin} IN IP4 0.0.0.0",
        "s=ice",
        "t=0 0",
        "a=nego-wait:0",
        "a=comelit-legacy-session:TCP",
        "a=comelit-session-id:MUX",
        "a=comelit-nego-aggressive:true",
        "c=IN IP4 0.0.0.0",
        f"m=audio {port} RTP/SAVPF 0 8",
        "b=RS:0",
        "b=RR:0",
        f"c=IN IP4 {default_ip}",
        "a=sendrecv",
        *candidates,
        "a=ice-role:a",
        f"a=ice-ufrag:{ufrag}",
        f"a=ice-pwd:{pwd}",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


def _validate(parsed: dict[str, object], data: bytes) -> None:
    if not data.endswith(b"\r\n"):
        _fail("NO_FINAL_CRLF")
    if data.count(b"\n") != data.count(b"\r\n"):
        _fail("NON_CRLF_LINE_ENDINGS")

    lines = [line for line in data.decode("ascii").split("\r\n") if line]
    port = int(parsed["port"])
    default_ip = str(parsed["default_ip"])
    candidates = list(parsed["candidates"])
    ufrag = str(parsed["ufrag"])
    pwd = str(parsed["pwd"])

    expected_prefix: list[str | None] = [
        "v=0",
        None,
        "s=ice",
        "t=0 0",
        "a=nego-wait:0",
        "a=comelit-legacy-session:TCP",
        "a=comelit-session-id:MUX",
        "a=comelit-nego-aggressive:true",
        "c=IN IP4 0.0.0.0",
        f"m=audio {port} RTP/SAVPF 0 8",
        "b=RS:0",
        "b=RR:0",
        f"c=IN IP4 {default_ip}",
        "a=sendrecv",
    ]

    if len(lines) < len(expected_prefix):
        _fail("OUTPUT_TOO_SHORT")

    for index, expected in enumerate(expected_prefix):
        if expected is None:
            if not re.fullmatch(
                r"o=- (\d+) \1 IN IP4 0\.0\.0\.0", lines[index]
            ):
                _fail("ORIGIN_INVALID")
        elif lines[index] != expected:
            _fail(f"PREFIX_MISMATCH_LINE_{index + 1}")

    if any(line.startswith("m=application ") for line in lines):
        _fail("APPLICATION_MLINE_PRESENT")

    out_candidates = [line for line in lines if line.startswith("a=candidate:")]
    if out_candidates != candidates:
        _fail("CANDIDATES_CHANGED")
    if f"a=ice-ufrag:{ufrag}" not in lines:
        _fail("UFRAG_CHANGED")
    if f"a=ice-pwd:{pwd}" not in lines:
        _fail("PWD_CHANGED")
    if lines[-3] != "a=ice-role:a":
        _fail("ROLE_POSITION")
    if not lines[-2].startswith("a=ice-ufrag:"):
        _fail("UFRAG_POSITION")
    if not lines[-1].startswith("a=ice-pwd:"):
        _fail("PWD_POSITION")


def transform_offer(raw_sdp: bytes) -> bytes:
    """Transform libnice SDP to the capture-proven Comelit SDP shape."""
    parsed = _parse_raw(raw_sdp)
    result = _build(parsed)
    _validate(parsed, result)
    return result
