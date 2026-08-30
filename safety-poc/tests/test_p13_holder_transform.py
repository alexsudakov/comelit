import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p13_holder_transform.py"
spec = importlib.util.spec_from_file_location("p13_holder_transform", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


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
        "target_name": "FixtureDoor",
        "channel_id_fixture": 7449,
        "write_count": 6,
        "bodies": [
            {"hex": b.hex(), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
            for b in bodies
        ],
    }


class P13HolderTransformTests(unittest.TestCase):
    def test_transform_embeds_six_bodies_and_markers(self):
        payload = make_payload()
        out = module.transform(BASELINE, payload)
        for i in range(1, 7):
            self.assertIn(f"p13_door_body_{i}", out)
        self.assertIn("P13_CTPP_OPEN_OUTCOME", out)
        self.assertIn("P13_DOOR_WRITE_COUNT", out)
        self.assertIn("P13_TEARDOWN=PASS", out)
        self.assertIn("P13_ONE_SHOT_MAX_INVOCATIONS=1", out)
        self.assertIn("P13_AUTO_RETRY_ALLOWED=false", out)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", out)

    def test_transform_rejects_wrong_write_count(self):
        payload = make_payload()
        payload["bodies"] = payload["bodies"][:5]
        with self.assertRaises(RuntimeError):
            module.transform(BASELINE, payload)

    def test_transform_rejects_bad_target_fingerprint(self):
        payload = make_payload()
        payload["target_fingerprint"] = "zz"
        with self.assertRaises(RuntimeError):
            module.transform(BASELINE, payload)

    def test_transform_contains_no_retry_loop(self):
        payload = make_payload()
        out = module.transform(BASELINE, payload)
        self.assertNotIn("for (guint attempt", out)
        self.assertNotIn("while (attempt", out)
        self.assertNotIn("while (retry", out)
        # Marker text is allowed; actual retry machinery is not.
        self.assertNotIn("p13_retry(", out)
        self.assertNotIn("retry_door", out)

    def test_transform_cli_surface_present(self):
        payload = make_payload()
        out = module.transform(BASELINE, payload)
        self.assertIn("--payload", out)
        self.assertIn("--operation-id", out)
        self.assertIn("--emit-ctpp-markers", out)

    def test_transform_embeds_payload_sha256(self):
        payload = make_payload()
        out = module.transform(BASELINE, payload)
        self.assertIn("P13_EXPECTED_PAYLOAD_SHA256", out)

    def test_transform_forbids_legacy_actuator_tokens(self):
        payload = make_payload()
        out = module.transform(BASELINE, payload)
        for token in ("OPEN_DOOR", "open_door", "create_door_message"):
            self.assertNotIn(token, out)

    def test_transform_requires_vip_token_value_never_emitted(self):
        payload = make_payload()
        out = module.transform(BASELINE, payload)
        self.assertIn("P13_VIP_TOKEN_VALUE_EMITTED=false", out)

    def test_transform_preserves_baseline_anchors(self):
        payload = make_payload()
        out = module.transform(BASELINE, payload)
        self.assertIn("uaut_response_timeout_cb", out)
        self.assertIn("pseudotcp_success_quit_cb", out)
        self.assertIn("try_send_echo_ack", out)


if __name__ == "__main__":
    unittest.main()
