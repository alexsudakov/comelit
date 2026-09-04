#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "generate_media_poc_v1.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "comelit_media_generator",
        SOURCE,
    )
    if spec is None or spec.loader is None:
        raise SystemExit("GENERATOR_LOAD=FAIL")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    original_replace_once = module.replace_once

    def scoped_replace_once(
        text: str,
        old: str,
        new: str,
        label: str,
    ) -> str:
        if label != "RECV_DEMUX":
            return original_replace_once(text, old, new, label)

        start_marker = "static void\nrecv_cb(\n"
        end_marker = "\n\n\nstatic gboolean\nabsolute_timeout_cb("

        start = text.find(start_marker)
        if start < 0:
            raise SystemExit("PATCH_RECV_DEMUX=FAIL callback_start=0")

        end = text.find(end_marker, start)
        if end < 0:
            raise SystemExit("PATCH_RECV_DEMUX=FAIL callback_end=0")

        callback = text[start:end]
        count = callback.count(old)
        if count != 1:
            raise SystemExit(f"PATCH_RECV_DEMUX=FAIL callback_count={count}")

        patched_callback = callback.replace(old, new, 1)
        print("GENERATOR_RECV_CALLBACK_SCOPE=PASS")
        return text[:start] + patched_callback + text[end:]

    module.replace_once = scoped_replace_once

    print("GENERATOR_LOAD=PASS")
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
