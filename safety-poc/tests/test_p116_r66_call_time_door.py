#!/usr/bin/env python3
"""P116/R66 call-time Door single-message contract tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
STUB_INCLUDE = Path(__file__).resolve().parent / "native" / "whole_tu_stub_include"
HARNESS_SOURCE = Path(__file__).resolve().parent / "native" / "p116_r66_call_time_door_host_harness.c"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r64_postcall_observability_transform as r64  # noqa: E402
import entrance_p116_r66_call_time_door_transform as r66  # noqa: E402


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_array(text: str, name: str) -> bytes:
    match = re.search(
        rf"static const guint8 {re.escape(name)}\[\] = \{{(?P<body>.*?)\}};",
        text,
        re.S,
    )
    if not match:
        raise AssertionError(f"missing array {name}")
    return bytes(int(item, 16) for item in re.findall(r"0x([0-9a-fA-F]{2})", match.group("body")))


def _reference_call_time_encoder(
    connection: int,
    sequence: int,
    ack: int,
    dest_logical: bytes,
    source_logical: bytes,
    apartment_base: bytes,
    relay_index: int = 1,
) -> bytes:
    """Independent PCAP-derived encoder model for relay_index=1.

    It intentionally does not reuse generated C helpers. The external model's
    LE32 relay_index maps byte-for-byte to relay low byte + three zero padding
    bytes for index 1, while the external counter slots map to our CTP
    connection/sequence/ack fields.
    """
    out = bytearray(48)
    out[0] = 0x40
    out[1] = 0x18
    out[2:4] = connection.to_bytes(2, "big")
    out[4] = sequence & 0xFF
    out[5] = ack & 0xFF
    out[6:8] = (13).to_bytes(2, "big")
    out[8:10] = (0x002D).to_bytes(2, "big")
    out[10:20] = dest_logical.ljust(10, b"\x00")[:10]
    out[20:24] = relay_index.to_bytes(4, "little")
    out[24:28] = b"\xff\xff\xff\xff"
    out[28:38] = source_logical.ljust(10, b"\x00")[:10]
    out[38:48] = apartment_base.ljust(10, b"\x00")[:10]
    return bytes(out)


def _c_bytes(data: bytes) -> str:
    return ", ".join(f"0x{byte:02x}" for byte in data)


def _extract_r66_region(candidate: str) -> str:
    return candidate.split(r66.BEGIN, 1)[1].split(r66.END, 1)[0].join((r66.BEGIN, r66.END))


def _parse_markers(stdout: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if re.fullmatch(r"[A-Z0-9_]+", key):
            markers[key] = value
    return markers


class P116R66CallTimeDoorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.r64_candidate = r64.transform(cls.source)
        cls.generated_a = r66.transform(cls.source)
        cls.generated_b = r66.transform(cls.source)
        cls.harness_source = HARNESS_SOURCE.read_text(encoding="utf-8")
        cls.harness_stdout = ""
        cls.harness_returncode = None
        cls.harness_markers: dict[str, str] = {}
        cls.harness_compile_stderr = ""
        cls.cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        cls.harness_compiled = False

        if cls.cc:
            expected = _reference_call_time_encoder(
                0x92A5,
                0x7E,
                0x21,
                b"00000643\0\0",
                b"000401177\0",
                b"00040117",
            )
            prelude = cls._build_harness_prelude(expected)
            cls.harness_tmp_obj = tempfile.TemporaryDirectory(prefix="p116-r66-harness-")
            tmp = Path(cls.harness_tmp_obj.name)
            combined = tmp / "r66_combined.c"
            combined.write_text(
                prelude + "\n" + _extract_r66_region(cls.generated_a) + "\n" + cls.harness_source,
                encoding="utf-8",
            )
            binary = tmp / "r66_harness"
            compile_result = subprocess.run(
                [cls.cc, "-std=c99", "-Wall", "-Wextra", "-pedantic", str(combined), "-o", str(binary)],
                text=True,
                capture_output=True,
            )
            cls.harness_compile_stderr = compile_result.stderr
            if compile_result.returncode == 0:
                cls.harness_compiled = True
                run = subprocess.run([str(binary)], text=True, capture_output=True)
                cls.harness_stdout = run.stdout
                cls.harness_returncode = run.returncode
                cls.harness_markers = _parse_markers(run.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "harness_tmp_obj"):
            cls.harness_tmp_obj.cleanup()

    @classmethod
    def _build_harness_prelude(cls, expected: bytes) -> str:
        standalone_defs = []
        for index in range(1, 6):
            r64_body = _parse_array(cls.r64_candidate, f"v4_door_operation_body_{index}")
            r66_body = _parse_array(cls.generated_a, f"v4_door_operation_body_{index}")
            standalone_defs.append(
                f"static const unsigned char R64_BODY_{index}[] = {{{_c_bytes(r64_body)}}};\n"
                f"static const unsigned char R66_BODY_{index}[] = {{{_c_bytes(r66_body)}}};\n"
                f"static const unsigned R64_BODY_{index}_LEN = {len(r64_body)}u;\n"
                f"static const unsigned R66_BODY_{index}_LEN = {len(r66_body)}u;"
            )

        return f"""
#include <stdio.h>
#include <string.h>
#include <stddef.h>

typedef int gboolean;
typedef unsigned int guint;
typedef unsigned char guint8;
typedef unsigned short guint16;
typedef unsigned int guint32;
typedef void *gpointer;
typedef long long gint64;

#define TRUE 1
#define FALSE 0
#define G_SOURCE_REMOVE FALSE
#define G_SOURCE_CONTINUE TRUE
#define G_USEC_PER_SEC 1000000

#define V4_APT_ADDRESS "00040117"
#define R35_CTP_LOGADDR_LEN 10u
#define R35_CTP_FLAG_DATA 0x40u
#define R35_CTP_VERSION 0x18u
#define V4_DOOR_SETTLE_MS 1000

typedef enum {{
    P12_STAGE_IDLE = 0,
    P12_STAGE_V4_LISTEN_RING
}} P12ReadonlyStage;

typedef enum {{
    P12_TX_NONE = 0,
    P12_TX_V4_DOOR_WRITE,
    P12_TX_CALL_TIME_DOOR
}} P12TxKind;

typedef enum {{
    V4_DOOR_IDLE = 0,
    V4_DOOR_SENDING,
    V4_DOOR_WAIT_SETTLE
}} V4DoorStage;

typedef enum {{
    V4_DOOR_TARGET_ENTRANCE = 0,
    V4_DOOR_TARGET_GATE
}} V4DoorTarget;

typedef enum {{
    R42_MEDIA_IDLE = 0,
    R42_MEDIA_ACTIVE
}} R42MediaStage;

typedef struct {{
    gboolean call_ready;
    guint call_ctp_connection;
    guint call_sequence;
    guint call_ack;
    guint call_generation;
    unsigned char dest_logical[R35_CTP_LOGADDR_LEN];
    unsigned char source_logical[R35_CTP_LOGADDR_LEN];
}} R35AttachedMediaSession;

static R35AttachedMediaSession g_r35_session;
static V4DoorTarget v4_door_target = V4_DOOR_TARGET_ENTRANCE;
static gboolean v4_listener_ready = FALSE;
static gboolean v4_registered = FALSE;
static guint16 v4_ctpp_channel_id = 0;
static P12ReadonlyStage p12_stage = P12_STAGE_IDLE;
static V4DoorStage v4_door_stage = V4_DOOR_IDLE;
static gboolean p12_tx_pending = FALSE;
static R42MediaStage r42_media_stage = R42_MEDIA_IDLE;
static gboolean v4_door_send_started = FALSE;
static guint v4_door_writes_sent = 0;
static gint64 v4_door_deadline_us = 0;
static gboolean failed = FALSE;
static void *loop = NULL;

static gboolean g_queue_accept = TRUE;
static gboolean g_flush_accept = TRUE;
static unsigned g_queued_frames = 0;
static unsigned g_legacy_standalone_writes = 0;
static P12TxKind g_last_kind = P12_TX_NONE;
static unsigned char g_last_body[128];
static unsigned g_last_body_len = 0;

static const unsigned char R66_EXPECTED_PACKET[] = {{{_c_bytes(expected)}}};
{chr(10).join(standalone_defs)}

static gboolean r35_call_ready(const R35AttachedMediaSession *s)
{{
    return s && s->call_ready;
}}

static void r35_write_be16(unsigned char *out, guint value)
{{
    out[0] = (unsigned char)((value >> 8) & 0xffu);
    out[1] = (unsigned char)(value & 0xffu);
}}

static guint16 r35_read_be16(const unsigned char *in)
{{
    return (guint16)((((guint16)in[0]) << 8) | ((guint16)in[1]));
}}

static guint16 read_le16(const unsigned char *in)
{{
    return (guint16)((((guint16)in[1]) << 8) | ((guint16)in[0]));
}}

static gboolean p12_queue_vip_frame(guint32 request_id, const guint8 *body, guint body_len, P12TxKind kind);
static gboolean p12_flush_tx(void);
static guint g_timeout_add(guint interval, gboolean (*callback)(gpointer), gpointer data);
static void v4_door_set_deadline(void);
static gboolean v4_door_settle_cb(gpointer data);
static void v4_door_emit_result(const char *result);
static void v4_door_reset(void);
static void g_main_loop_quit(void *main_loop);

static int r66_standalone_bodies_match(void)
{{
    return R64_BODY_1_LEN == R66_BODY_1_LEN && memcmp(R64_BODY_1, R66_BODY_1, R64_BODY_1_LEN) == 0 &&
           R64_BODY_2_LEN == R66_BODY_2_LEN && memcmp(R64_BODY_2, R66_BODY_2, R64_BODY_2_LEN) == 0 &&
           R64_BODY_3_LEN == R66_BODY_3_LEN && memcmp(R64_BODY_3, R66_BODY_3, R64_BODY_3_LEN) == 0 &&
           R64_BODY_4_LEN == R66_BODY_4_LEN && memcmp(R64_BODY_4, R66_BODY_4, R64_BODY_4_LEN) == 0 &&
           R64_BODY_5_LEN == R66_BODY_5_LEN && memcmp(R64_BODY_5, R66_BODY_5, R64_BODY_5_LEN) == 0;
}}

static gboolean p12_queue_vip_frame(guint32 request_id, const guint8 *body, guint body_len, P12TxKind kind)
{{
    (void)request_id;
    if (!g_queue_accept || p12_tx_pending || body_len > sizeof(g_last_body))
        return FALSE;
    g_queued_frames++;
    g_last_kind = kind;
    g_last_body_len = body_len;
    memcpy(g_last_body, body, body_len);
    if (kind == P12_TX_V4_DOOR_WRITE)
        g_legacy_standalone_writes++;
    return TRUE;
}}

static gboolean p12_flush_tx(void)
{{
    return g_flush_accept;
}}

static guint g_timeout_add(guint interval, gboolean (*callback)(gpointer), gpointer data)
{{
    (void)interval;
    (void)callback;
    (void)data;
    return 1u;
}}

static void v4_door_set_deadline(void)
{{
    v4_door_deadline_us = 1;
}}

static gboolean v4_door_settle_cb(gpointer data)
{{
    (void)data;
    return G_SOURCE_REMOVE;
}}

static void v4_door_emit_result(const char *result)
{{
    printf("V4_DOOR_RESULT=%s\\n", result);
}}

static void v4_door_reset(void)
{{
    v4_door_stage = V4_DOOR_IDLE;
    v4_door_writes_sent = 0;
    v4_door_send_started = FALSE;
}}

static void g_main_loop_quit(void *main_loop)
{{
    (void)main_loop;
}}
"""

    def require_harness(self) -> None:
        if not self.cc:
            self.skipTest("no C compiler available")
        if not self.harness_compiled:
            self.fail("R66 native harness failed to compile:\n" + self.harness_compile_stderr[:4000])

    def test_transform_is_deterministic_and_layered_on_r64(self) -> None:
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertEqual(_sha256(self.generated_a), _sha256(self.generated_b))
        source = Path(r66.__file__).read_text(encoding="utf-8")
        self.assertIn("r64.transform(source)", source)
        self.assertIn(r64.BEGIN, self.generated_a)
        self.assertIn(r66.BEGIN, self.generated_a)

    def test_active_attached_entrance_selects_one_call_time_tx(self) -> None:
        candidate = self.generated_a
        self.assertIn("P12_TX_CALL_TIME_DOOR", candidate)
        self.assertIn("V4_DOOR_PATH=CALL_TIME_SINGLE", candidate)
        self.assertIn("V4_CALL_TIME_DOOR_COMMAND_ACCEPTED=true", candidate)
        self.assertIn("V4_CALL_TIME_DOOR_QUEUED=true", candidate)
        self.assertIn("V4_CALL_TIME_DOOR_SENT=true", candidate)
        self.assertIn("V4_CALL_TIME_DOOR_WRITE_COUNT=1", candidate)
        self.assertIn("r42_media_stage == R42_MEDIA_ACTIVE", candidate)
        self.assertIn("v4_door_target == V4_DOOR_TARGET_ENTRANCE", candidate)
        self.assertEqual(candidate.count("P12_TX_CALL_TIME_DOOR"), 3)

    def test_real_tick_order_preserves_selected_path_across_sending_transition(self) -> None:
        candidate = self.generated_a
        tick_start = candidate.index("v4_door_tick_cb(gpointer data)")
        tick_end = candidate.index("p12_process_post_uaut", tick_start)
        tick = candidate[tick_start:tick_end]

        select_at = tick.index(
            "g_r66_call_time_door_selected = r66_call_time_door_eligible();"
        )
        sending_at = tick.index("v4_door_stage = V4_DOOR_SENDING;")
        queue_at = tick.index("if (g_r66_call_time_door_selected)", sending_at)

        self.assertLess(select_at, sending_at)
        self.assertLess(sending_at, queue_at)
        self.assertIn("v4_door_stage == V4_DOOR_IDLE", candidate)
        self.assertIn("v4_door_stage == V4_DOOR_SENDING", candidate)

        region = candidate.split(r66.BEGIN, 1)[1].split(r66.END, 1)[0]
        queue_start = region.index("r66_queue_call_time_door(void)")
        queue_tail = region[queue_start:region.index(
            "r66_call_time_door_note_control_response", queue_start
        )]
        self.assertIn("r66_call_time_door_queue_ready()", queue_tail)
        self.assertNotIn("r66_call_time_door_eligible()", queue_tail)
        self.assertIn("V4_DOOR_PATH=CALL_TIME_SINGLE", queue_tail)

    def test_native_harness_cases_a_through_h_execute_generated_region(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        for marker in (
            "R66_CASE_A_ELIGIBLE_ONE_CALL_TIME_FRAME",
            "R66_CASE_A_REAL_TICK_ORDER_SINGLE_MESSAGE",
            "R66_CASE_B_BYTE_EQUALITY",
            "R66_CASE_B_INVERSION_DETECTED",
            "R66_CASE_C_SEQUENCE_ADVANCES_ON_TX_COMPLETE",
            "R66_CASE_C_QUEUE_FAILURE_DOES_NOT_ADVANCE",
            "R66_CASE_D_SELECTOR_FALSE_MEDIA_INACTIVE",
            "R66_CASE_D_REAL_TICK_FALLS_BACK_STANDALONE",
            "R66_CASE_D_STANDALONE_BODIES_BYTE_IDENTICAL",
            "R66_CASE_E_GATE_NOT_PROMOTED",
            "R66_CASE_F_PENDING_TX_BLOCKS",
            "R66_CASE_F_NO_RETRY",
            "R66_CASE_G_STALE_CALL_FALSE",
            "R66_CASE_G_R35_NOT_READY_FALSE",
            "R66_CASE_H_STDOUT_BOUNDED_MARKERS_ONLY",
        ):
            with self.subTest(marker=marker):
                self.assertEqual(self.harness_markers.get(marker), "PASS")
        self.assertEqual(self.harness_markers["R66_CASE_A_QUEUED_FRAMES"], "1")
        self.assertEqual(self.harness_markers["R66_CASE_A_QUEUED_KIND"], "CALL_TIME_DOOR")
        self.assertEqual(self.harness_markers["R66_CASE_A_LEGACY_STANDALONE_WRITES"], "0")
        self.assertEqual(self.harness_markers["R66_CASE_C_SEQUENCE_BEFORE"], "126")
        self.assertEqual(self.harness_markers["R66_CASE_C_SEQUENCE_WIRE"], "126")
        self.assertEqual(self.harness_markers["R66_CASE_C_SEQUENCE_AFTER"], "127")
        self.assertEqual(self.harness_markers["R66_CASE_C_QUEUE_FAILURE_BEFORE"], "126")
        self.assertEqual(self.harness_markers["R66_CASE_C_QUEUE_FAILURE_AFTER"], "126")

    def test_native_harness_ack_marker_is_derived_with_inversion(self) -> None:
        self.require_harness()
        self.assertEqual(self.harness_markers.get("R66_ACK_MARKER_TRUE_DERIVED"), "PASS")
        self.assertEqual(self.harness_markers.get("R66_ACK_MARKER_FALSE_WITHOUT_RESPONSE"), "PASS")
        self.assertEqual(self.harness_markers.get("R66_ACK_GENERIC_NOT_DOOR_SPECIFIC"), "PASS")
        self.assertIn("CALL_TIME_DOOR_ACK_OBSERVED=true", self.harness_stdout)
        self.assertIn("CALL_TIME_DOOR_ACK_OBSERVED=false", self.harness_stdout)
        self.assertIn("V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false", self.harness_stdout)
        self.assertNotIn("protocol_acked", self.harness_stdout)
        self.assertNotIn("physical_effect_asserted", self.harness_stdout)

    def test_native_harness_stdout_exposes_no_raw_ids_addresses_or_payloads(self) -> None:
        self.require_harness()
        self.assertNotRegex(self.harness_stdout, r"00040117|000401177|00000643")
        self.assertNotRegex(self.harness_stdout, r"92a5|0x92a5|37541")
        self.assertNotRegex(self.harness_stdout, r"3456|0x3456|13398")
        self.assertNotRegex(self.harness_stdout, r"\b[0-9a-fA-F]{24,}\b")
        self.assertNotIn("PAYLOAD", self.harness_stdout.upper())
        self.assertNotIn("HEX", self.harness_stdout.upper())

    def test_serializer_layout_matches_independent_reference_encoder(self) -> None:
        connection = 0x92A5
        sequence = 0x7E
        ack = 0x21
        dest = b"00000643\0\0"
        source = b"000401177\0"
        apt = b"00040117"
        expected = _reference_call_time_encoder(connection, sequence, ack, dest, source, apt)

        self.assertEqual(len(expected), 48)
        self.assertEqual(expected[0:2], b"\x40\x18")
        self.assertEqual(expected[2:4], b"\x92\xa5")
        self.assertEqual(expected[4], sequence)
        self.assertEqual(expected[5], ack)
        self.assertEqual(expected[6:8], b"\x00\x0d")
        self.assertEqual(expected[8:10], b"\x00\x2d")
        self.assertEqual(expected[10:20], dest)
        self.assertEqual(expected[20:24], b"\x01\x00\x00\x00")
        self.assertEqual(expected[24:28], b"\xff\xff\xff\xff")
        self.assertEqual(expected[28:38], source)
        self.assertEqual(expected[38:48], b"00040117\0\0")

        region = self.generated_a.split(r66.BEGIN, 1)[1].split(r66.END, 1)[0]
        for needle in (
            "R66_CALL_TIME_DOOR_PACKET_LEN 48u",
            "R66_CALL_TIME_DOOR_INNER_LEN 13u",
            "R66_CALL_TIME_DOOR_OPCODE 0x002Du",
            "out[0] = (unsigned char)R35_CTP_FLAG_DATA;",
            "out[1] = (unsigned char)R35_CTP_VERSION;",
            "r35_write_be16(out + 2, s->call_ctp_connection",
            "out[4] = (unsigned char)(s->call_sequence",
            "out[5] = (unsigned char)(s->call_ack",
            "memcpy(out + 10, s->dest_logical",
            "out[20] = (unsigned char)R66_CALL_TIME_DOOR_RELAY_ENTRANCE;",
            "memcpy(out + 28, s->source_logical",
            "r66_write_padded_ascii(out + 38, V4_APT_ADDRESS",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, region)

    def test_sequence_contract_and_queue_failure_behavior(self) -> None:
        candidate = self.generated_a
        self.assertIn(
            "g_r66_call_time_door_sequence_before = g_r35_session.call_sequence & 0xffu;",
            candidate,
        )
        self.assertIn(
            "g_r66_call_time_door_sequence_after =\n"
            "        (g_r66_call_time_door_sequence_before + 1u) & 0xffu;",
            candidate,
        )
        self.assertIn(
            "g_r35_session.call_sequence = g_r66_call_time_door_sequence_after & 0xffu;",
            candidate,
        )
        self.assertIn("r66_call_time_door_tx_completed", candidate)
        region = candidate.split(r66.BEGIN, 1)[1].split(r66.END, 1)[0]
        queue_failure_tail = region.split("if (!queued)\n        return FALSE;", 1)[0]
        self.assertNotIn("g_r35_session.call_sequence =", queue_failure_tail)
        self.assertIn("CALL_SEQUENCE_BEFORE=%u", candidate)
        self.assertIn("CALL_SEQUENCE_AFTER=%u", candidate)

    def test_inactive_media_falls_back_to_standalone_and_bytes_unchanged(self) -> None:
        for index in range(1, 6):
            with self.subTest(index=index):
                self.assertEqual(
                    _parse_array(self.r64_candidate, f"v4_door_operation_body_{index}"),
                    _parse_array(self.generated_a, f"v4_door_operation_body_{index}"),
                )
        self.assertIn(
            "g_r66_call_time_door_selected = r66_call_time_door_eligible();",
            self.generated_a,
        )
        self.assertIn("if (g_r66_call_time_door_selected)", self.generated_a)
        self.assertIn("if (!v4_door_queue_write(1))", self.generated_a)
        self.assertIn("v4_door_queue_write(v4_door_write_index + 1)", self.generated_a)

    def test_gate_collision_and_stale_call_fail_closed(self) -> None:
        region = self.generated_a.split(r66.BEGIN, 1)[1].split(r66.END, 1)[0]
        self.assertIn("v4_door_target == V4_DOOR_TARGET_ENTRANCE", region)
        self.assertNotIn("V4_DOOR_TARGET_GATE &&", region)
        self.assertIn("!p12_tx_pending", region)
        self.assertIn("r35_call_ready(&g_r35_session)", region)
        self.assertIn("r42_media_stage == R42_MEDIA_ACTIVE", region)
        self.assertNotIn("v4_door_queue_write", region)
        self.assertNotIn("P12_TX_V4_DOOR_WRITE", region)

    def test_whole_tu_compiles_with_stub_headers(self) -> None:
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if not cc:
            self.skipTest("no C compiler available")
        with tempfile.TemporaryDirectory(prefix="p116-r66-tu-") as tmp:
            tu = Path(tmp) / "r66-whole-tu.c"
            tu.write_text(self.generated_a, encoding="utf-8")
            result = subprocess.run(
                [
                    cc,
                    "-std=gnu11",
                    "-fsyntax-only",
                    "-Wall",
                    "-Wextra",
                    "-Werror=implicit-function-declaration",
                    "-Werror=implicit-int",
                    "-I",
                    str(STUB_INCLUDE),
                    str(tu),
                ],
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr[:4000])
        self.assertNotIn(": error:", result.stderr)


if __name__ == "__main__":
    unittest.main()
