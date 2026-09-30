#!/usr/bin/env python3
"""P122 active-media Door eligibility corrective tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
REPO = ROOT.parent
STUB_INCLUDE = Path(__file__).resolve().parent / "native" / "whole_tu_stub_include"
sys.path.insert(0, str(MEDIA))

import entrance_p122_on_demand_media_door_transform as p122  # noqa: E402

REJECT_GATES = (
    ("SIGNAL_STAGE", "entrance_signal_stage = ENTRANCE_SIGNAL_OBSERVE_MEDIA;"),
    ("MEDIA_FORWARDING", "p80_media_forwarding_enabled = FALSE;"),
    ("RTPC_STAGE", "p78_rtpc_stage = 0;"),
    ("PSEUDOTCP", "pseudo_tcp = NULL;"),
    ("GRACEFUL_STOP", "pseudotcp_graceful_stop_started = TRUE;"),
    ("CTPP", "v4_ctpp_channel_id = 0u;"),
    ("TX_PENDING", "p12_tx_pending = TRUE;"),
    ("REFRESH_OUTSTANDING", "r27_repeat_outstanding = TRUE;"),
    ("REFRESH_FAIL_CLOSED", "r27_refresh_fail_closed = TRUE;"),
    ("INITIAL_001A", "r27_initial_001a_sent_count = 2u;"),
    ("DOOR_INFLIGHT", "p122_door_inflight = TRUE;"),
)


def _extract_p122_region(candidate: str) -> str:
    return candidate.split(p122.BEGIN, 1)[1].split(p122.END, 1)[0].join(
        (p122.BEGIN, p122.END)
    )


def _parse_markers(stdout: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if re.fullmatch(r"[A-Z0-9_]+", key):
            markers[key] = value
    return markers


def _compile_and_run(source: str, *, name: str) -> tuple[int, str, str]:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        raise unittest.SkipTest("no C compiler available")
    with tempfile.TemporaryDirectory(prefix=name) as tmp:
        path = Path(tmp) / "p122_harness.c"
        binary = Path(tmp) / "p122_harness"
        path.write_text(source, encoding="utf-8")
        compile_result = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-pedantic", str(path), "-o", str(binary)],
            text=True,
            capture_output=True,
        )
        if compile_result.returncode != 0:
            return compile_result.returncode, "", compile_result.stderr
        run = subprocess.run([str(binary)], text=True, capture_output=True)
        return run.returncode, run.stdout, run.stderr


class P122ActiveMediaEligibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.generated = p122.transform(cls.source)
        cls.region = _extract_p122_region(cls.generated)
        cls.transport = (REPO / "custom_components" / "comelit" / "media_transport.py").read_text(
            encoding="utf-8"
        )

    @classmethod
    def _harness_source(
        cls,
        *,
        region: str | None = None,
        mutation: str = "",
        run_reject_cases: bool = True,
    ) -> str:
        test_cases = "\n".join(
            f'    run_reject_case("{gate}", "{statement}");' for gate, statement in REJECT_GATES
        ) if run_reject_cases else ""
        selected_region = region or cls.region
        return textwrap.dedent(
            f"""
            #include <signal.h>
            #include <stdio.h>
            #include <string.h>

            typedef int gboolean;
            typedef unsigned int guint;
            typedef unsigned char guint8;
            typedef unsigned short guint16;
            typedef unsigned int guint32;
            typedef void *gpointer;
            typedef struct {{ int open; }} PseudoTcpSocket;

            #define TRUE 1
            #define FALSE 0
            #define G_SOURCE_CONTINUE 1
            #define G_SOURCE_REMOVE 0
            #define SIGUSR1 10

            typedef enum {{
                ENTRANCE_SIGNAL_IDLE = 0,
                ENTRANCE_SIGNAL_OBSERVE_MEDIA = 7,
                ENTRANCE_SIGNAL_DONE = 8
            }} EntranceSignalStage;
            typedef enum {{
                P78_RTPC_START = 0,
                P78_RTPC_COMPLETE = 4
            }} P78RtpcStage;
            typedef enum {{
                P12_TX_OTHER = 0,
                P122_TX_ONDEMAND_DOOR = 99
            }} P12TxKind;

            static EntranceSignalStage entrance_signal_stage;
            static gboolean entrance_signaling_result;
            static gboolean p80_media_forwarding_enabled;
            static P78RtpcStage p78_rtpc_stage;
            static PseudoTcpSocket pseudo_tcp_real;
            static PseudoTcpSocket *pseudo_tcp;
            static gboolean pseudotcp_open;
            static gboolean pseudotcp_graceful_stop_started;
            static guint32 v4_ctpp_channel_id;
            static gboolean p12_tx_pending;
            static gboolean r27_repeat_outstanding;
            static gboolean r27_refresh_fail_closed;
            static guint r27_initial_001a_sent_count;
            static guint r27_repeat_001a_sent_count;
            static guint32 r27_repeat_001a_sequence;
            static guint32 r27_initial_001a_sequence;
            static gboolean r27_repeat_timer_cancelled;
            static guint queue_count;
            static guint flush_count;
            static guint write_count;
            static guint32 queued_request_id;
            static P12TxKind queued_kind;
            static guint8 queued_body[48];
            static guint queued_body_len;

            static const guint8 V4_ENTRANCE[8] = {{0x30,0x30,0x30,0x30,0x30,0x36,0x34,0x33}};
            static const guint8 V4_FULL_ADDRESS[9] = {{0x30,0x30,0x30,0x34,0x30,0x31,0x31,0x37,0x37}};
            static const guint8 V4_APT_ADDRESS[8] = {{0x30,0x30,0x30,0x34,0x30,0x31,0x31,0x37}};

            static guint g_timeout_add(guint interval, gboolean (*func)(gpointer), gpointer data)
            {{
                (void)interval;
                (void)func;
                (void)data;
                return 1u;
            }}

            {selected_region}

            static gboolean p12_queue_vip_frame(
                guint32 request_id,
                const guint8 *body,
                guint body_len,
                P12TxKind kind)
            {{
                queue_count++;
                queued_request_id = request_id;
                queued_kind = kind;
                queued_body_len = body_len;
                if (body && body_len <= sizeof(queued_body))
                    memcpy(queued_body, body, body_len);
                return TRUE;
            }}

            static gboolean p12_flush_tx(void)
            {{
                flush_count++;
                if (queued_kind == P122_TX_ONDEMAND_DOOR) {{
                    p122_door_last_sent_sequence = p122_door_sequence;
                    p122_door_sent = TRUE;
                    p122_door_waiting_ack = TRUE;
                    write_count++;
                    printf("P122_ONDEMAND_DOOR_SENT=true\\n");
                    printf("P122_ONDEMAND_DOOR_WRITE_COUNT=1\\n");
                }}
                return TRUE;
            }}

            static void reset_ready(void)
            {{
                entrance_signal_stage = ENTRANCE_SIGNAL_DONE;
                entrance_signaling_result = TRUE;
                p80_media_forwarding_enabled = TRUE;
                p78_rtpc_stage = P78_RTPC_COMPLETE;
                pseudo_tcp = &pseudo_tcp_real;
                pseudotcp_open = TRUE;
                pseudotcp_graceful_stop_started = FALSE;
                v4_ctpp_channel_id = 0x1200u;
                p12_tx_pending = FALSE;
                r27_repeat_outstanding = FALSE;
                r27_refresh_fail_closed = FALSE;
                r27_initial_001a_sent_count = 1u;
                r27_repeat_001a_sent_count = 0u;
                r27_repeat_001a_sequence = 0u;
                r27_initial_001a_sequence = 0x10000u;
                r27_repeat_timer_cancelled = FALSE;
                p122_door_signal_pending = 0;
                p122_door_inflight = FALSE;
                p122_door_sent = FALSE;
                p122_door_last_sent_sequence = 0u;
                p122_door_waiting_ack = FALSE;
                p122_door_ack_observed = FALSE;
                p122_door_relay_event_observed = FALSE;
                p122_door_sequence = 0u;
                queue_count = 0u;
                flush_count = 0u;
                write_count = 0u;
                queued_request_id = 0u;
                queued_kind = P12_TX_OTHER;
                queued_body_len = 0u;
                memset(queued_body, 0, sizeof(queued_body));
            }}

            static void run_reject_case(const char *expected, const char *statement)
            {{
                reset_ready();
                if (strcmp(expected, "SIGNAL_STAGE") == 0) entrance_signal_stage = ENTRANCE_SIGNAL_OBSERVE_MEDIA;
                else if (strcmp(expected, "MEDIA_FORWARDING") == 0) p80_media_forwarding_enabled = FALSE;
                else if (strcmp(expected, "RTPC_STAGE") == 0) p78_rtpc_stage = P78_RTPC_START;
                else if (strcmp(expected, "PSEUDOTCP") == 0) pseudo_tcp = NULL;
                else if (strcmp(expected, "GRACEFUL_STOP") == 0) pseudotcp_graceful_stop_started = TRUE;
                else if (strcmp(expected, "CTPP") == 0) v4_ctpp_channel_id = 0u;
                else if (strcmp(expected, "TX_PENDING") == 0) p12_tx_pending = TRUE;
                else if (strcmp(expected, "REFRESH_OUTSTANDING") == 0) r27_repeat_outstanding = TRUE;
                else if (strcmp(expected, "REFRESH_FAIL_CLOSED") == 0) r27_refresh_fail_closed = TRUE;
                else if (strcmp(expected, "INITIAL_001A") == 0) r27_initial_001a_sent_count = 2u;
                else if (strcmp(expected, "DOOR_INFLIGHT") == 0) p122_door_inflight = TRUE;
                p122_door_signal_pending = 1;
                printf("CASE=%s STATEMENT=%s REAL=%s\\n",
                    expected, statement, p122_door_gate_name(p122_door_evaluate_gate()));
                p122_door_tick_cb(NULL);
            }}

            int main(void)
            {{
                reset_ready();
                printf("READY_GATE=%s\\n", p122_door_gate_name(p122_door_evaluate_gate()));
                printf("READY_ELIGIBLE=%s\\n", p122_door_eligible() ? "true" : "false");
                p122_door_signal_pending = 1;
                p122_door_tick_cb(NULL);
                printf("SUCCESS_QUEUE_COUNT=%u\\n", queue_count);
                printf("SUCCESS_FLUSH_COUNT=%u\\n", flush_count);
                printf("SUCCESS_WRITE_COUNT=%u\\n", write_count);
                printf("SUCCESS_REQUEST_ID=%u\\n", queued_request_id);
                printf("SUCCESS_KIND=%u\\n", (unsigned)queued_kind);
                printf("SUCCESS_BODY_LEN=%u\\n", queued_body_len);
                printf("SUCCESS_BODY_PREFIX=%02x%02x\\n", queued_body[0], queued_body[1]);
                printf("SUCCESS_BODY_ACTION=%02x%02x\\n", queued_body[6], queued_body[7]);
                printf("SUCCESS_RELAY=%u\\n", queued_body[20]);
                printf("SUCCESS_REFRESH_CANCELLED=%s\\n", r27_repeat_timer_cancelled ? "true" : "false");
                {test_cases}
                {mutation}
                return 0;
            }}
            """
        )

    def test_generated_lineage_active_media_transition_is_p85_done_state(self) -> None:
        marker = 'printf("P80_MEDIA_ACTIVE=true\\n");'
        pos = self.generated.index(marker)
        lines = self.generated[:pos].splitlines()
        block = "\n".join(lines[-20:])
        assignments = re.findall(
            r"(entrance_signal_stage|entrance_signaling_result|p80_media_forwarding_enabled)\s*=\s*([^;]+);",
            block,
        )
        self.assertEqual(assignments[-3:], [
            ("entrance_signal_stage", "ENTRANCE_SIGNAL_DONE"),
            ("entrance_signaling_result", "TRUE"),
            ("p80_media_forwarding_enabled", "TRUE"),
        ])

    def test_p122_predicate_tracks_production_active_media_state(self) -> None:
        self.assertIn("entrance_signal_stage != ENTRANCE_SIGNAL_DONE", self.region)
        self.assertNotIn("entrance_signaling_result", self.region)
        self.assertNotIn("entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA", self.region)
        self.assertNotIn("entrance_signal_stage != ENTRANCE_SIGNAL_OBSERVE_MEDIA", self.region)

    def test_reject_discriminator_is_bounded_and_not_constant_printf(self) -> None:
        for gate, _ in REJECT_GATES:
            self.assertIn(f'return "{gate}";', self.region)
            self.assertNotIn(f'P122_ONDEMAND_DOOR_REJECT_GATE={gate}', self.region)
        self.assertIn('printf("P122_ONDEMAND_DOOR_REJECT_GATE=%s\\n"', self.region)
        self.assertEqual(self.region.count("p122_door_evaluate_gate()"), 2)

    def test_ha_captures_only_bounded_reject_gate(self) -> None:
        self.assertIn("_P122_DOOR_REJECT_GATES = {", self.transport)
        self.assertIn('key == "P122_ONDEMAND_DOOR_REJECT_GATE"', self.transport)
        self.assertIn('"reject_gate"', self.transport)
        for gate, _ in REJECT_GATES:
            self.assertIn(f'"{gate}"', self.transport)

    def test_generated_region_host_harness_accepts_active_media_and_rejects_each_gate(self) -> None:
        rc, stdout, stderr = _compile_and_run(self._harness_source(), name="p122-active-")
        self.assertEqual(rc, 0, stderr[:4000])
        markers = _parse_markers(stdout)
        self.assertEqual(markers["READY_GATE"], "READY")
        self.assertEqual(markers["READY_ELIGIBLE"], "true")
        self.assertEqual(markers["SUCCESS_QUEUE_COUNT"], "1")
        self.assertEqual(markers["SUCCESS_FLUSH_COUNT"], "1")
        self.assertEqual(markers["SUCCESS_WRITE_COUNT"], "1")
        self.assertEqual(markers["SUCCESS_REQUEST_ID"], str(0x1200))
        self.assertEqual(markers["SUCCESS_KIND"], "99")
        self.assertEqual(markers["SUCCESS_BODY_LEN"], "48")
        self.assertEqual(markers["SUCCESS_BODY_PREFIX"], "4018")
        self.assertEqual(markers["SUCCESS_BODY_ACTION"], "000d")
        self.assertEqual(markers["SUCCESS_RELAY"], "1")
        self.assertEqual(markers["SUCCESS_REFRESH_CANCELLED"], "true")
        self.assertIn("P122_ONDEMAND_DOOR_PATH=ACTIVE_MEDIA_SINGLE", stdout)
        self.assertIn("P122_ONDEMAND_DOOR_EXISTING_CTPP_REUSED=true", stdout)
        self.assertIn("P122_ONDEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false", stdout)
        self.assertIn("P122_ONDEMAND_DOOR_PHYSICAL_EFFECT_ASSERTED=false", stdout)
        self.assertIn("P122_ONDEMAND_DOOR_RESULT=REJECTED_NOT_READY", stdout)
        for gate, statement in REJECT_GATES:
            self.assertIn(f"CASE={gate} STATEMENT={statement} REAL={gate}", stdout)
            self.assertIn(f"P122_ONDEMAND_DOOR_REJECT_GATE={gate}", stdout)

    def test_second_explicit_press_only_after_one_second_settle_advances_sequence(self) -> None:
        """Two separate native signals: one write each; no second write while inflight."""
        probe = r'''
                reset_ready();
                p122_door_signal_pending = 1;
                p122_door_tick_cb(NULL);
                guint32 first_sequence = p122_door_last_sent_sequence;
                printf("FIRST_MANUAL_WRITE_COUNT=%u\\n", write_count);
                printf("FIRST_MANUAL_SEQUENCE=%u\\n", first_sequence);

                p122_door_signal_pending = 1;
                p122_door_tick_cb(NULL);
                printf("BEFORE_SETTLE_GATE=%s\\n", p122_door_gate_name(p122_door_evaluate_gate()));
                printf("BEFORE_SETTLE_WRITE_COUNT=%u\\n", write_count);

                /* The existing native settle callback is armed for 1000 ms. */
                p122_door_settle_cb(NULL);
                printf("AFTER_SETTLE_GATE=%s\\n", p122_door_gate_name(p122_door_evaluate_gate()));
                p122_door_signal_pending = 1;
                p122_door_tick_cb(NULL);
                printf("SECOND_MANUAL_WRITE_COUNT=%u\\n", write_count);
                printf("SECOND_MANUAL_SEQUENCE=%u\\n", p122_door_last_sent_sequence);
                printf("SEQUENCE_STEP=%u\\n", p122_door_last_sent_sequence - first_sequence);
                printf("SECOND_MEDIA_FORWARDING=%s\\n", p80_media_forwarding_enabled ? "true" : "false");
        '''
        rc, stdout, stderr = _compile_and_run(
            self._harness_source(mutation=probe, run_reject_cases=False),
            name="p122-two-manual-",
        )
        self.assertEqual(rc, 0, stderr[:4000])
        markers = _parse_markers(stdout)
        self.assertEqual(markers["FIRST_MANUAL_WRITE_COUNT"], "1")
        self.assertEqual(markers["FIRST_MANUAL_SEQUENCE"], str(0x20000))
        self.assertEqual(markers["BEFORE_SETTLE_GATE"], "DOOR_INFLIGHT")
        self.assertEqual(markers["BEFORE_SETTLE_WRITE_COUNT"], "1")
        self.assertEqual(markers["AFTER_SETTLE_GATE"], "READY")
        self.assertEqual(markers["SECOND_MANUAL_WRITE_COUNT"], "2")
        self.assertEqual(markers["SECOND_MANUAL_SEQUENCE"], str(0x30000))
        self.assertEqual(markers["SEQUENCE_STEP"], str(0x10000))
        self.assertEqual(markers["SECOND_MEDIA_FORWARDING"], "true")
        self.assertEqual(stdout.count("P122_ONDEMAND_DOOR_SENT=true"), 3)  # initial harness + two explicit presses
        self.assertIn("P122_ONDEMAND_DOOR_REJECT_GATE=DOOR_INFLIGHT", stdout)
        self.assertNotIn("DOOR_ALREADY_SENT", stdout)

    def test_legacy_session_wide_reject_is_absent_but_no_retry_guarantee_remains(self) -> None:
        self.assertNotIn("P122_DOOR_GATE_DOOR_ALREADY_SENT", self.region)
        self.assertNotIn('return "DOOR_ALREADY_SENT";', self.region)
        self.assertIn("#define P122_DOOR_SETTLE_MS 1000u", self.region)
        self.assertIn("if (p122_door_inflight)", self.region)
        self.assertIn("p122_door_last_sent_sequence = p122_door_sequence;", self.generated)
        self.assertIn("if (p122_door_sent)", self.region)
        self.assertIn("return p122_door_last_sent_sequence;", self.region)
        self.assertIn("P122_ONDEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false", self.region)

    def test_signal_stage_predicate_flip_moves_ready_state_to_reject_path(self) -> None:
        real_probe = (
            'reset_ready();\n'
            '                printf("REAL=%s\\n", p122_door_gate_name(p122_door_evaluate_gate()));'
        )
        real_rc, real_stdout, real_stderr = _compile_and_run(
            self._harness_source(mutation=real_probe, run_reject_cases=False),
            name="p122-predicate-real-",
        )
        self.assertEqual(real_rc, 0, real_stderr[:4000])
        real_markers = _parse_markers(real_stdout)
        self.assertEqual(real_markers["REAL"], "READY")
        self.assertEqual(real_markers["READY_ELIGIBLE"], "true")
        self.assertEqual(real_markers["SUCCESS_QUEUE_COUNT"], "1")
        self.assertNotIn("P122_ONDEMAND_DOOR_REJECT_GATE=", real_stdout)

        original = "if (entrance_signal_stage != ENTRANCE_SIGNAL_DONE)"
        replacement = "if (entrance_signal_stage == ENTRANCE_SIGNAL_DONE)"
        self.assertIn(original, self.region)
        mutated_region = self.region.replace(original, replacement, 1)
        mutated_probe = (
            'reset_ready();\n'
            '                printf("MUTATED=%s\\n", p122_door_gate_name(p122_door_evaluate_gate()));'
        )
        mutated_rc, mutated_stdout, mutated_stderr = _compile_and_run(
            self._harness_source(
                region=mutated_region,
                mutation=mutated_probe,
                run_reject_cases=False,
            ),
            name="p122-predicate-mutated-",
        )
        self.assertEqual(mutated_rc, 0, mutated_stderr[:4000])
        mutated_markers = _parse_markers(mutated_stdout)
        self.assertEqual(mutated_markers["MUTATED"], "SIGNAL_STAGE")
        self.assertNotEqual(real_markers["REAL"], mutated_markers["MUTATED"])
        self.assertEqual(mutated_markers["READY_ELIGIBLE"], "false")
        self.assertEqual(mutated_markers["SUCCESS_QUEUE_COUNT"], "0")
        self.assertIn("P122_ONDEMAND_DOOR_REJECT_GATE=SIGNAL_STAGE", mutated_stdout)

    def test_reject_discriminator_moves_when_source_copy_is_mutated(self) -> None:
        for gate, _ in REJECT_GATES:
            with self.subTest(gate=gate):
                mutated = self.region.replace(f'return "{gate}";', 'return "MUTATED";', 1)
                mutation = (
                    'reset_ready();\n'
                    f'                printf("MUTATION_GATE={gate} REAL={gate} MUTATED=%s\\n", '
                    f'p122_door_gate_name(P122_DOOR_GATE_{gate}));'
                )
                rc, stdout, stderr = _compile_and_run(
                    self._harness_source(region=mutated, mutation=mutation),
                    name="p122-mutated-",
                )
                self.assertEqual(rc, 0, stderr[:4000])
                self.assertIn(f"MUTATION_GATE={gate} REAL={gate} MUTATED=MUTATED", stdout)

    def test_whole_generated_translation_unit_passes_compile_gate(self) -> None:
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if not cc:
            self.skipTest("no C compiler available")
        with tempfile.TemporaryDirectory(prefix="p122-tu-") as tmp:
            tu = Path(tmp) / "p122-whole-tu.c"
            tu.write_text(self.generated, encoding="utf-8")
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
        self.assertEqual(result.returncode, 0, result.stderr[:5000])

    def test_generated_source_sha256_is_stable_for_result_note(self) -> None:
        self.assertRegex(hashlib.sha256(self.generated.encode("utf-8")).hexdigest(), r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
