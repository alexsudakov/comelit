from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

POC_ROOT = Path(__file__).resolve().parents[1]
SRC = POC_ROOT / "src"
SCRIPTS = POC_ROOT / "scripts"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


canonicalizer = load_script_module("p13_canonicalize_payload", SCRIPTS / "p13_canonicalize_payload.py")
holder_transform = load_script_module("p13_holder_transform_blocker_test", SCRIPTS / "p13_holder_transform.py")

BASELINE = r'''#include <glib.h>
#define POST_ACK_CAPTURE_MAX 256
static guint8 uaut_open[23];
static guint uaut_open_offset = 0;
static gboolean pseudotcp_success_quit_cb(gpointer data);
static gboolean
uaut_response_timeout_cb(gpointer data)
{
    return TRUE;
}
static gboolean
try_parse_uaut_response(void)
{
    if (uaut_response_seen)
        return TRUE;

    g_timeout_add(
        250,
        pseudotcp_success_quit_cb,
        NULL
    );

    return TRUE;
}
static void
pseudotcp_writable_cb(PseudoTcpSocket *tcp, gpointer data)
{
    if (!try_send_echo_ack() ||
        !try_send_uaut_open()) {
        failed = TRUE;
    }
}
static gboolean
pseudotcp_success_quit_cb(gpointer data)
{
    (void)data;
    return G_SOURCE_REMOVE;
}
'''


def make_payload() -> dict:
    bodies = [bytes([i + 1]) * 12 for i in range(6)]
    return {
        "schema": 1,
        "ucfg_sha256": "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7",
        "target_index": 0,
        "target_fingerprint": "f" * 64,
        "target_name": "72к4.3",
        "channel_id_fixture": 7449,
        "write_count": 6,
        "bodies": [
            {"hex": body.hex(), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            for body in bodies
        ],
    }


class P13PayloadRuntimeIdentityRegressionTests(unittest.TestCase):
    def test_pretty_prepared_payload_becomes_exact_holder_runtime_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "real-door-payloads.json"
            payload = make_payload()
            # Match prepare_p13_real_payloads.py: pretty JSON, sorted keys,
            # ensure_ascii=False and a trailing newline.
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
            before = path.read_bytes()

            runtime_sha = canonicalizer.canonicalize_payload(path)
            runtime_bytes = path.read_bytes()
            self.assertNotEqual(before, runtime_bytes)
            self.assertEqual(runtime_sha, hashlib.sha256(runtime_bytes).hexdigest())
            self.assertEqual(
                runtime_bytes,
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

            transformed = holder_transform.transform(
                BASELINE,
                json.loads(runtime_bytes.decode("utf-8")),
            )
            self.assertIn(
                f'#define P13_EXPECTED_PAYLOAD_SHA256 "{runtime_sha}"',
                transformed,
            )


class P13OperationIdBindingRegressionTests(unittest.TestCase):
    def test_cli_operation_id_overrides_wrong_parent_env_for_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            payload = make_payload()
            payload_path = tmp / "payload.json"
            payload_path.write_bytes(canonicalizer.canonical_payload_bytes(payload))
            os.chmod(payload_path, 0o600)

            counter = tmp / "counter"
            counter.write_text("0", encoding="utf-8")
            wrapper = tmp / "wrapper"
            wrapper.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "[ \"${P13_OPERATION_ID:-}\" = \"op-exact\" ] || exit 91\n"
                f"N=$(cat '{counter}' 2>/dev/null || echo 0)\n"
                f"echo $((N + 1)) > '{counter}'\n"
                "printf '%s\\n' 'P13_CTPP_OPEN_OUTCOME=OPENED'\n"
                "printf '%s\\n' 'P13_DOOR_WRITE_COUNT=6'\n"
                "printf '%s\\n' 'P13_CTPP_CLOSE=PASS'\n"
                "printf '%s\\n' 'P13_TEARDOWN=PASS'\n",
                encoding="utf-8",
            )
            os.chmod(wrapper, 0o700)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(SRC)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["P13_REQUIRE_ROOT_OWNER"] = "0"
            env["P13_APPROVAL"] = "I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST"
            # Regression condition: inherited ambient value is wrong. The
            # runner must replace it with --operation-id before wrapper Popen.
            env["P13_OPERATION_ID"] = "wrong-parent-value"

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "comelit_safety_poc.p13_one_shot_physical",
                    "--db",
                    str(tmp / "poc.sqlite3"),
                    "--operation-id",
                    "op-exact",
                    "--target-fingerprint",
                    "f" * 64,
                    "--min-interval-seconds",
                    "0",
                    "--wrapper",
                    str(wrapper),
                    "--wrapper-sha256",
                    hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                    "--payload",
                    str(payload_path),
                    "--payload-sha256",
                    hashlib.sha256(payload_path.read_bytes()).hexdigest(),
                    "--audit",
                    str(tmp / "audit.jsonl"),
                    "--head",
                    "h" * 40,
                    "--tree",
                    "t" * 40,
                    "--run-dir",
                    str(tmp / "run"),
                ],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["operation_id"], "op-exact")
            self.assertEqual(counter.read_text(encoding="utf-8").strip(), "1")


if __name__ == "__main__":
    unittest.main()
