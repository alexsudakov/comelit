import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p12_holder_transform_safe.py"
spec = importlib.util.spec_from_file_location("p12_holder_transform_safe", SCRIPT)
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


class P12HolderTransformSafeTests(unittest.TestCase):
    def test_premature_timer_is_replaced_and_final_timer_survives(self):
        ucfg = b'{"message":"get-configuration","message-type":"request"}\n'
        out = module.transform(BASELINE, ucfg)
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
        self.assertEqual(out.count("if (!p12_begin_auth())"), 1)
        self.assertIn("!p12_flush_tx()", out)
        self.assertIn("P12_READONLY_TRANSACTION=PASS", out)
        self.assertIn("ACTUATOR_COMMAND_ATTEMPTED=false", out)

    def test_ucfg_template_requires_real_lf(self):
        with self.assertRaises(RuntimeError):
            module.transform(BASELINE, b'{"message":"get-configuration"}\\n')


if __name__ == "__main__":
    unittest.main()
