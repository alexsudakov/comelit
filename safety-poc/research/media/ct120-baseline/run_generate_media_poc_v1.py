#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import runpy
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "generate_media_poc_v1.py"

OLD = '    recv_anchor = """    if (!pseudo_tcp) {\\n"""\n'
NEW = '''    recv_anchor = """    /*\\n     * STUN/ICE control packets are consumed internally by libnice.\\n     * Data reaching this callback is application payload\\n     * carried by the selected ICE component.\\n     */\\n    if (!pseudo_tcp) {\\n"""\n'''


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")

    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"GENERATOR_RECV_ANCHOR_FIX=FAIL count={count}")

    patched = text.replace(OLD, NEW, 1)

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
        print("GENERATOR_RECV_ANCHOR_FIX=PASS")
        namespace = runpy.run_path(str(temp_path), run_name="__main__")
        _ = namespace
    finally:
        temp_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
