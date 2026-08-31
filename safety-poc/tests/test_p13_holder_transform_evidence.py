import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p13_holder_transform_evidence.py"
spec = importlib.util.spec_from_file_location("p13_holder_transform_evidence", SCRIPT)
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
    bodies = [bytes([index + 1]) * 12 for index in range(6)]
    return {
        "schema": 1,
        "ucfg_sha256": "d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7",
        "target_index": 0,
        "target_fingerprint": "f" * 64,
        "target_name": "FixtureDoor",
        "channel_id_fixture": 7449,
        "write_count": 6,
        "bodies": [
            {
                "hex": body.hex(),
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
            for body in bodies
        ],
    }


class P13HolderTransformEvidenceTests(unittest.TestCase):
    def test_adds_ctpp_only_raw_rx_evidence(self):
        out = module.transform(BASELINE, make_payload(), "012345678")
        self.assertIn("p13_log_ctpp_rx_evidence", out)
        self.assertIn("P13_CTPP_RX_EVIDENCE ts_us=", out)
        self.assertIn("body_sha256=%s body_hex=%s", out)
        self.assertIn(
            "if (p13_ctpp_open_ok &&\n            request_id == ctpp_channel_id)",
            out,
        )

    def test_response_marker_does_not_claim_ack(self):
        out = module.transform(BASELINE, make_payload(), "012345678")
        self.assertIn("P13_DOOR_RESPONSE_SEEN=true", out)
        self.assertIn("P13_DOOR_INBOUND_FRAME_OBSERVED=true", out)
        self.assertNotIn("P13_DOOR_WRITE_%u_ACKED=true", out)
        self.assertNotIn("P13_DOOR_WRITE_REQUEST_ID=FAIL", out)

    def test_safe_peer_timing_is_preserved(self):
        out = module.transform(BASELINE, make_payload(), "012345678")
        self.assertEqual(out.count("g_timeout_add(200, p13_register_settle_cb, NULL);"), 1)
        self.assertEqual(out.count("g_timeout_add(1000, p13_post_writes_settle_cb, NULL);"), 1)
        self.assertIn("p13_writes_sent = p13_write_index;", out)

    def test_rx_evidence_is_observational_only(self):
        out = module.transform(BASELINE, make_payload(), "012345678")
        block_start = out.index("if (request_id == ctpp_channel_id &&")
        block_end = out.index("if (p13_stage == P13_STAGE_WAIT_CTPP_CLOSE_RESPONSE)")
        block = out[block_start:block_end]
        self.assertIn("P13_DOOR_RESPONSE_SEEN=true", block)
        self.assertNotIn("p13_queue_door_write", block)
        self.assertNotIn("p13_writes_sent =", block)

    def test_no_retry_surface_added(self):
        out = module.transform(BASELINE, make_payload(), "012345678")
        self.assertNotIn("p13_retry(", out)
        self.assertNotIn("retry_door", out)
        self.assertIn("P13_AUTO_RETRY_ALLOWED=false", out)


if __name__ == "__main__":
    unittest.main()
