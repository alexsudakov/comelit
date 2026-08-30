import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p13_holder_transform_safe.py"
spec = importlib.util.spec_from_file_location("p13_holder_transform_safe", SCRIPT)
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


class P13HolderTransformSafeTests(unittest.TestCase):
    def test_premature_uaut_quit_is_replaced_and_final_timer_survives(self):
        out = module.transform(BASELINE, make_payload(), "012345678")
        self.assertNotIn(
            "g_timeout_add(\n        250,\n        pseudotcp_success_quit_cb",
            out,
        )
        self.assertEqual(
            out.count(
                "g_timeout_add (\n                250,\n                pseudotcp_success_quit_cb"
            ),
            1,
        )
        self.assertEqual(out.count("if (!p13_begin_auth())"), 1)
        self.assertIn("!p13_flush_tx()", out)

    def test_ctpp_open_uses_canonical_extension_shape(self):
        out = module.transform(BASELINE, make_payload(), "012345678")
        self.assertEqual(out.count("guint8 body[30];"), 1)
        self.assertIn("write_le32(body + 4, 7);", out)
        self.assertIn("memcpy(body + 8, P13_CHANNEL_NAME, 4);", out)
        self.assertIn("write_le16(body + 12, ctpp_requested_channel_id);", out)
        self.assertIn("body[14] = 0;", out)
        self.assertIn("body[15] = 0;", out)
        self.assertIn(
            "write_le32(body + 16, (guint32)sizeof(ctpp_extension_payload));",
            out,
        )
        self.assertIn("memcpy(body + 20, ctpp_extension_payload", out)
        # Synthetic fixture only: 9 ASCII digits plus NUL.
        self.assertIn(
            "0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x00",
            out,
        )

    def test_open_response_may_have_length_checked_extension(self):
        out = module.transform(BASELINE, make_payload(), "012345678")
        self.assertIn("if (expected_opcode == 4 && body_len != 12)", out)
        self.assertIn("if (expected_opcode == 2 && body_len > 12)", out)
        self.assertIn("extension_len != body_len - 16u", out)

    def test_ctpp_address_is_derived_from_unique_vip_object(self):
        doc = {
            "outer": {
                "vip": {
                    "apt-address": "01234567",
                    "apt-subaddress": "8",
                    "user-parameters": {},
                }
            }
        }
        self.assertEqual(module._ctpp_address_from_doc(doc), "012345678")

    def test_ctpp_address_rejects_wrong_shape(self):
        with self.assertRaises(RuntimeError):
            module.transform(BASELINE, make_payload(), "123")
        with self.assertRaises(RuntimeError):
            module._ctpp_address_from_doc(
                {
                    "vip": {
                        "apt-address": "abcdefgh",
                        "apt-subaddress": "x",
                        "user-parameters": {},
                    }
                }
            )

    def test_no_retry_surface_added(self):
        out = module.transform(BASELINE, make_payload(), "012345678")
        self.assertNotIn("p13_retry(", out)
        self.assertNotIn("retry_door", out)
        self.assertIn("P13_AUTO_RETRY_ALLOWED=false", out)


if __name__ == "__main__":
    unittest.main()
