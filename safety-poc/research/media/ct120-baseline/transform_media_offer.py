#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SDP_MODULE = REPO / "custom_components" / "comelit" / "sdp.py"


def _load_transform():
    spec = importlib.util.spec_from_file_location("comelit_sdp_standalone", SDP_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("SDP_MODULE_LOAD_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.transform_offer


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: transform_media_offer.py RAW_OFFER COMELIT_OFFER", file=sys.stderr)
        return 2

    raw_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    if not raw_path.is_file() or raw_path.stat().st_size == 0:
        print("MEDIA_OFFER_TRANSFORM=FAIL raw_offer_missing", file=sys.stderr)
        return 3

    transform_offer = _load_transform()
    raw = raw_path.read_bytes()
    wire = transform_offer(raw)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(wire)
    out_path.chmod(0o600)

    lines = [line for line in wire.decode("ascii").split("\r\n") if line]
    candidate_count = sum(line.startswith("a=candidate:") for line in lines)
    has_audio = any(line.startswith("m=audio ") for line in lines)
    has_ufrag = any(line.startswith("a=ice-ufrag:") for line in lines)
    has_pwd = any(line.startswith("a=ice-pwd:") for line in lines)
    has_nego = any(line == "a=nego-wait:0" for line in lines)
    has_session = any(line == "a=comelit-session-id:MUX" for line in lines)

    print("MEDIA_OFFER_TRANSFORM=PASS")
    print(f"COMELIT_OFFER_LINES={len(lines)}")
    print(f"COMELIT_OFFER_AUDIO_PRESENT={str(has_audio).lower()}")
    print(f"COMELIT_OFFER_UFRAG_PRESENT={str(has_ufrag).lower()}")
    print(f"COMELIT_OFFER_PWD_PRESENT={str(has_pwd).lower()}")
    print(f"COMELIT_OFFER_CANDIDATE_COUNT={candidate_count}")
    print(f"COMELIT_OFFER_NEGO_WAIT_PRESENT={str(has_nego).lower()}")
    print(f"COMELIT_OFFER_SESSION_ID_PRESENT={str(has_session).lower()}")

    if not (has_audio and has_ufrag and has_pwd and candidate_count > 0 and has_nego and has_session):
        print("MEDIA_OFFER_TRANSFORM_GATE=FAIL", file=sys.stderr)
        return 4

    print("MEDIA_OFFER_TRANSFORM_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
