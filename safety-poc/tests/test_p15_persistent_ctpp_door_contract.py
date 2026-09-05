import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = (
    ROOT
    / "safety-poc/research/door/v1_5_3"
    / "comelit-v4-persistent-ctpp-door.c"
)


class PersistentCtppDoorContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SRC.read_text(encoding="utf-8")

    def test_no_secondary_ctpp_lifecycle(self):
        for token in (
            "P12_TX_V4_DOOR_OPEN_CTPP",
            "P12_TX_V4_DOOR_CLOSE_CTPP",
            "v4_door_queue_open",
            "v4_door_queue_close",
            "V4_DOOR_WAIT_OPEN",
            "V4_DOOR_WAIT_CLOSE",
        ):
            self.assertNotIn(token, self.text)

    def test_persistent_ctpp_is_reused(self):
        self.assertIn(
            "p12_queue_vip_frame(\n"
            "            v4_ctpp_channel_id,",
            self.text,
        )
        self.assertIn("V4_DOOR_EXISTING_CTPP_REUSED=true", self.text)
        self.assertIn("!v4_registered", self.text)
        self.assertIn("v4_ctpp_channel_id == 0", self.text)

    def test_exact_five_operation_bodies(self):
        bodies = []
        for index in range(1, 6):
            match = re.search(
                rf"static const guint8 "
                rf"v4_door_operation_body_{index}\[\] = "
                rf"\{{(.*?)\n\}};",
                self.text,
                re.S,
            )
            self.assertIsNotNone(match)
            values = re.findall(r"0x([0-9a-fA-F]{2})", match.group(1))
            bodies.append(bytes(int(v, 16) for v in values))

        self.assertEqual(
            [len(body) for body in bodies],
            [32, 32, 48, 32, 32],
        )
        self.assertEqual(
            [int.from_bytes(body[:2], "little") for body in bodies],
            [0x1800, 0x1820, 0x18C0, 0x1800, 0x1820],
        )
        self.assertIn(
            "static const guint v4_door_write_count = 5;",
            self.text,
        )

    def test_inbound_frames_do_not_advance_door(self):
        self.assertNotIn("v4_door_process_frame", self.text)
        self.assertNotIn("V4_DOOR_WRITE_%u_ACKED=true", self.text)
        self.assertNotIn('v4_door_emit_result("ACKED")', self.text)

    def test_tx_completion_drives_sequence(self):
        self.assertIn(
            "if (v4_door_write_index < v4_door_write_count)",
            self.text,
        )
        self.assertIn(
            "v4_door_queue_write(v4_door_write_index + 1)",
            self.text,
        )
        self.assertIn(
            "g_timeout_add(\n"
            "                        V4_DOOR_SETTLE_MS,\n"
            "                        v4_door_settle_cb,",
            self.text,
        )

    def test_result_marker_is_emitted_after_all_result_metadata(self):
        emit = re.search(
            r"static void\nv4_door_emit_result\(const gchar \*state\)"
            r"(.*?)\n\}",
            self.text,
            re.S,
        )
        self.assertIsNotNone(emit)
        body = emit.group(1)

        result_pos = body.index("V4_DOOR_RESULT=%s")
        self.assertLess(body.index("V4_DOOR_WRITE_COUNT=%u"), result_pos)
        self.assertLess(
            body.index("V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false"),
            result_pos,
        )
        self.assertLess(
            body.index("V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false"),
            result_pos,
        )

    def test_rejected_not_ready_result_marker_is_terminal(self):
        start = self.text.index("if (!v4_listener_ready ||")
        end = self.text.index(
            'printf("V4_DOOR_COMMAND_ACCEPTED=true\\n");',
            start,
        )
        body = self.text[start:end]

        result_pos = body.index(
            "V4_DOOR_RESULT=REJECTED_NOT_READY"
        )

        self.assertLess(
            body.index(
                "V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false"
            ),
            result_pos,
        )
        self.assertLess(
            body.index(
                "V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false"
            ),
            result_pos,
        )

    def test_terminal_state_is_conservative(self):
        settle = re.search(
            r"static gboolean\nv4_door_settle_cb\(gpointer data\)"
            r"(.*?)\n\}",
            self.text,
            re.S,
        )
        self.assertIsNotNone(settle)
        self.assertIn(
            'v4_door_emit_result("UNKNOWN_OUTCOME")',
            settle.group(1),
        )
        self.assertIn(
            "V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false",
            settle.group(1),
        )
        self.assertIn(
            "V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
            self.text,
        )
        self.assertIn(
            "V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
