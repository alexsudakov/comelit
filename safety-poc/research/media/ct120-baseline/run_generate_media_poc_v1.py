#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import runpy
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "generate_media_poc_v1.py"

BLOCK_RE = re.compile(
    r"    recv_anchor = .*?"
    r"    src = replace_once\(src, recv_anchor, recv_insert, \"RECV_DEMUX\"\)\n",
    re.DOTALL,
)

REPLACEMENT = '''    recv_anchor = """    if (sid != stream_id ||
        component_id != 1) {
        return;
    }

    /*
     * STUN/ICE control packets are consumed internally by libnice.
     * Data reaching this callback is application payload
     * carried by the selected ICE component.
     */
    if (!pseudo_tcp) {
"""
    recv_insert = """    if (sid != stream_id ||
        component_id != 1) {
        return;
    }

    /*
     * STUN/ICE control packets are consumed internally by libnice.
     * Data reaching this callback is application payload
     * carried by the selected ICE component.
     */
    /* Raw ViP media is multiplexed beside PseudoTCP on the same ICE component. */
    if (v4_media_try_handle_raw((const guint8 *)buf, len))
        return;

    if (!pseudo_tcp) {
"""
    src = replace_once(src, recv_anchor, recv_insert, "RECV_DEMUX")
'''


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")

    matches = list(BLOCK_RE.finditer(text))
    if len(matches) != 1:
        raise SystemExit(f"GENERATOR_RECV_BLOCK_FIX=FAIL count={len(matches)}")

    patched = BLOCK_RE.sub(lambda _: REPLACEMENT, text, count=1)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".py",
        prefix="comelit-media-generator-",
        dir=HERE,
        delete=False,
    ) as handle:
        handle.write(patched)
        temp_path = Path(handle.name)

    try:
        print("GENERATOR_RECV_BLOCK_FIX=PASS")
        namespace = runpy.run_path(str(temp_path), run_name="__main__")
        _ = namespace
    finally:
        temp_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
