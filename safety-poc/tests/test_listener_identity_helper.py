#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "safety-poc" / "research" / "ha_gateway" / "v1" / "comelit-listener-identity.sh"
FRAGMENT = ROOT / "safety-poc" / "research" / "ha_gateway" / "v1" / "gateway-dispatch-fragment.txt"
OBSERVER = ROOT / "safety-poc" / "research" / "media" / "v1" / "listener_readonly_observer.py"
LISTENER_EXE = "/config/custom_components/comelit/native/comelit-v4"
HOST_LISTENER_EXE = "/usr/share/hassio/homeassistant/custom_components/comelit/native/comelit-v4"
MEDIA_EXE = "/config/custom_components/comelit/native/comelit-media"
RESEARCH_EXE = "/config/custom_components/comelit/native/comelit-media-research-stage7-v2"


def parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
    return out


class ProcFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "sys" / "kernel" / "random").mkdir(parents=True)
        (root / "sys" / "kernel" / "random" / "boot_id").write_text(
            "00000000-0000-4000-8000-000000000001\n", encoding="utf-8"
        )
        (root / "net").mkdir()
        self.write_udp()
        (root / "net" / "tcp").write_text(self.net_header(), encoding="utf-8")
        (root / "net" / "tcp6").write_text(self.net_header(), encoding="utf-8")
        (root / "net" / "udp6").write_text(self.net_header(), encoding="utf-8")

    @staticmethod
    def stat(pid: int, start: int) -> str:
        return f"{pid} (comelit-v4) " + " ".join(["S", *["0"] * 18, str(start), "0", "0"]) + "\n"

    @staticmethod
    def net_header() -> str:
        return "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"

    def write_udp(self, inode: int = 111, port_hex: str = "1F90") -> None:
        line = f"   0: 0100007F:{port_hex} 00000000:0000 07 00000000:00000000 00:00000000 00000000 0 0 {inode}\n"
        (self.root / "net" / "udp").write_text(self.net_header() + line, encoding="utf-8")

    def add_proc(
        self,
        pid: int,
        *,
        start: int = 1000,
        exe: str = LISTENER_EXE,
        argv: bytes = b"",
        socket_inode: int | None = 111,
        cwd: str | None = None,
    ) -> None:
        proc = self.root / str(pid)
        (proc / "fd").mkdir(parents=True)
        (proc / "exe").symlink_to(exe)
        (proc / "cmdline").write_bytes(argv)
        (proc / "stat").write_text(self.stat(pid, start), encoding="utf-8")
        if cwd is not None:
            (proc / "cwd").symlink_to(cwd)
        if socket_inode is not None:
            (proc / "fd" / "3").symlink_to(f"socket:[{socket_inode}]")


class ListenerIdentityHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_obj.name)
        self.proc = self.tmp / "proc"
        self.proc.mkdir()
        self.fixture = ProcFixture(self.proc)

    def tearDown(self) -> None:
        self.tmp_obj.cleanup()

    def run_helper(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "COMELIT_PROC_ROOT": str(self.proc)}
        return subprocess.run([str(HELPER), *args], text=True, capture_output=True, env=env, timeout=10)

    def identity(self) -> dict[str, str]:
        result = self.run_helper()
        return parse_kv(result.stdout)

    def test_comelit_v4_empty_argv_identifies_listener(self) -> None:
        self.fixture.add_proc(100)
        out = self.identity()
        self.assertEqual(out["STATUS"], "PASS")
        self.assertEqual(out["LISTENER_PID"], "100")
        self.assertEqual(out["MATCH_RULE"], "exe-allowlist-comelit-v4-source-derived")
        self.assertEqual(out["LISTENER_SOCKET_PRESENT"], "true")
        self.assertEqual(out["LISTENER_SOCKET_PROTOCOL"], "udp")
        self.assertEqual(out["LISTENER_SOCKET_LOCAL"], "127.0.0.1:8080")

    def test_listener_run_dir_corroboration_unknown_when_not_observable(self) -> None:
        self.fixture.add_proc(100)
        self.assertEqual(self.identity()["LISTENER_RUN_DIR_CORROBORATION"], "UNKNOWN")

    def test_listener_run_dir_corroboration_true_when_cwd_inside_p2p_run_dir(self) -> None:
        self.fixture.add_proc(100, cwd="/run/comelit-p2p")
        self.assertEqual(self.identity()["LISTENER_RUN_DIR_CORROBORATION"], "true")

    def test_no_listener_process_not_found(self) -> None:
        self.fixture.add_proc(200, exe="/bin/sh", argv=b"/bin/sh\0")
        out = self.identity()
        self.assertEqual(out["STATUS"], "NOT_FOUND")
        self.assertEqual(out["CANDIDATE_COUNT"], "0")

    def test_comelit_media_empty_argv_is_not_listener(self) -> None:
        self.fixture.add_proc(100, exe=MEDIA_EXE, argv=b"")
        out = self.identity()
        self.assertEqual(out["STATUS"], "NOT_FOUND")
        self.assertNotEqual(out["STATUS"], "PASS")
        self.assertEqual(out["CANDIDATE_COUNT"], "0")

    def test_media_helper_never_wins_when_listener_present(self) -> None:
        self.fixture.add_proc(100, exe=MEDIA_EXE, argv=b"")
        self.fixture.add_proc(101, exe=LISTENER_EXE, argv=b"", start=2000, socket_inode=None)
        out = self.identity()
        self.assertEqual(out["STATUS"], "PASS")
        self.assertEqual(out["LISTENER_PID"], "101")
        self.assertEqual(out["CANDIDATE_COUNT"], "1")

    def test_two_matching_processes_ambiguous(self) -> None:
        self.fixture.add_proc(100)
        self.fixture.add_proc(101, start=2000, socket_inode=None)
        out = self.identity()
        self.assertEqual(out["STATUS"], "AMBIGUOUS")
        self.assertEqual(out["CANDIDATE_COUNT"], "2")

    def test_same_pid_and_starttime_same_generation(self) -> None:
        self.fixture.add_proc(100, start=1000)
        first = self.identity()["LISTENER_PROCESS_GENERATION"]
        shutil.rmtree(self.proc / "100")
        self.fixture.add_proc(100, start=1000)
        self.assertEqual(self.identity()["LISTENER_PROCESS_GENERATION"], first)

    def test_same_pid_changed_starttime_new_generation(self) -> None:
        self.fixture.add_proc(100, start=1000)
        first = self.identity()["LISTENER_PROCESS_GENERATION"]
        shutil.rmtree(self.proc / "100")
        self.fixture.add_proc(100, start=1001)
        self.assertNotEqual(self.identity()["LISTENER_PROCESS_GENERATION"], first)

    def test_changed_pid_new_generation(self) -> None:
        self.fixture.add_proc(100, start=1000)
        first = self.identity()["LISTENER_PROCESS_GENERATION"]
        shutil.rmtree(self.proc / "100")
        self.fixture.add_proc(101, start=1000)
        self.assertNotEqual(self.identity()["LISTENER_PROCESS_GENERATION"], first)

    def test_same_socket_same_fingerprint(self) -> None:
        self.fixture.add_proc(100)
        first = self.identity()["LISTENER_SOCKET_FINGERPRINT_SHA256"]
        self.assertEqual(self.identity()["LISTENER_SOCKET_FINGERPRINT_SHA256"], first)

    def test_socket_inode_changed_new_fingerprint(self) -> None:
        self.fixture.add_proc(100, socket_inode=111)
        first = self.identity()["LISTENER_SOCKET_FINGERPRINT_SHA256"]
        shutil.rmtree(self.proc / "100" / "fd")
        (self.proc / "100" / "fd").mkdir()
        (self.proc / "100" / "fd" / "3").symlink_to("socket:[222]")
        self.fixture.write_udp(inode=222)
        self.assertNotEqual(self.identity()["LISTENER_SOCKET_FINGERPRINT_SHA256"], first)

    def test_local_port_changed_new_fingerprint(self) -> None:
        self.fixture.add_proc(100, socket_inode=111)
        first = self.identity()["LISTENER_SOCKET_FINGERPRINT_SHA256"]
        self.fixture.write_udp(inode=111, port_hex="1F91")
        self.assertNotEqual(self.identity()["LISTENER_SOCKET_FINGERPRINT_SHA256"], first)

    def test_research_helper_process_is_not_listener(self) -> None:
        self.fixture.add_proc(100, exe=RESEARCH_EXE, argv=b"")
        self.assertEqual(self.identity()["STATUS"], "NOT_FOUND")

    def test_media_and_mini_app_helpers_are_not_listener(self) -> None:
        self.fixture.add_proc(100, exe=MEDIA_EXE, argv=b"")
        self.assertEqual(self.identity()["STATUS"], "NOT_FOUND")

    def test_listener_allowlist_contains_v4_and_not_media_positive_entry(self) -> None:
        text = HELPER.read_text(encoding="utf-8")
        line = next(
            line for line in text.splitlines() if line.startswith("COMELIT_LISTENER_EXE_ALLOWLIST=")
        )
        self.assertIn("native/comelit-v4", line)
        self.assertIn(HOST_LISTENER_EXE, line)
        self.assertNotIn("native/comelit-media", line)

    def test_secrets_never_appear_in_output(self) -> None:
        canary = "SECRET_CANARY_TOKEN_123"
        self.fixture.add_proc(100, argv=f"{LISTENER_EXE}\0{canary}\0".encode())
        (self.proc / "100" / "environ").write_text(f"TOKEN={canary}\n", encoding="utf-8")
        result = self.run_helper()
        self.assertNotIn(canary, result.stdout)
        self.assertIn("SECRETS_EMITTED=false", result.stdout)

    def test_arbitrary_argument_rejected(self) -> None:
        for arg in ("100", "/proc/100", "comelit-v4"):
            with self.subTest(arg=arg):
                result = self.run_helper(arg)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("STATUS=UNSUPPORTED_ARGUMENT", result.stdout)

    def test_no_writes_performed(self) -> None:
        self.fixture.add_proc(100)
        before = sorted(
            (p.relative_to(self.proc).as_posix(), p.stat(follow_symlinks=False).st_mtime_ns) for p in self.proc.rglob("*")
        )
        out = self.identity()
        after = sorted(
            (p.relative_to(self.proc).as_posix(), p.stat(follow_symlinks=False).st_mtime_ns) for p in self.proc.rglob("*")
        )
        self.assertEqual(out["WRITES_PERFORMED"], "false")
        self.assertEqual(after, before)

    def test_gateway_fragment_has_no_argument_pass_through(self) -> None:
        text = FRAGMENT.read_text(encoding="utf-8")
        self.assertIn("readonly-listener-identity)", text)
        self.assertIn("exec /config/tools/comelit-listener-identity.sh", text)
        self.assertNotIn('"$@"', text)
        self.assertNotIn("$1", text)
        self.assertIn("takes zero user arguments", text)

    def test_gateway_fragment_only_adds_branch_and_preserves_existing_semantics(self) -> None:
        text = FRAGMENT.read_text(encoding="utf-8")
        self.assertEqual(text.count("readonly-listener-identity)"), 1)
        for verb in ("status", "check", "logs", "logs-follow", "deploy <sha>", "rollback", "restart USER_APPROVED"):
            self.assertIn(verb, text)
        self.assertIn("are not modified", text)


class ListenerReadonlyObserverIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_obj.name)

    def tearDown(self) -> None:
        self.tmp_obj.cleanup()

    def capture(self, name: str, *, ready: str = "true", generation: str = "gen1", socket: str = "sock1") -> Path:
        path = self.tmp / name
        path.write_text(
            "\n".join(
                [
                    "STATUS=PASS",
                    f"LISTENER_READY={ready}",
                    "LISTENER_PID=100",
                    f"LISTENER_PROCESS_GENERATION={generation}",
                    f"LISTENER_SOCKET_FINGERPRINT_SHA256={socket}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def run_observer(self, *args: str) -> dict[str, str]:
        result = subprocess.run([sys.executable, str(OBSERVER), *args], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return parse_kv(result.stdout)

    def test_observer_reports_stable_identity_comparison(self) -> None:
        before = self.capture("before.env")
        after = self.capture("after.env")
        out = self.run_observer("--identity-before", str(before), "--identity-after", str(after))
        self.assertEqual(out["PROCESS_GENERATION_CHANGED"], "false")
        self.assertEqual(out["SOCKET_FINGERPRINT_CHANGED"], "false")
        self.assertEqual(out["CONFLICT_DETECTION_SUFFICIENT"], "true")

    def test_observer_reports_pid_generation_changed(self) -> None:
        before = self.capture("before.env", generation="gen1")
        after = self.capture("after.env", generation="gen2")
        out = self.run_observer("--identity-before", str(before), "--identity-after", str(after))
        self.assertEqual(out["PROCESS_GENERATION_CHANGED"], "true")
        self.assertEqual(out["LISTENER_RECOVERY_OBSERVED"], "true")

    def test_observer_reports_socket_changed(self) -> None:
        before = self.capture("before.env", socket="sock1")
        after = self.capture("after.env", socket="sock2")
        out = self.run_observer("--identity-before", str(before), "--identity-after", str(after))
        self.assertEqual(out["SOCKET_FINGERPRINT_CHANGED"], "true")
        self.assertEqual(out["LISTENER_RECOVERY_OBSERVED"], "true")

    def test_observer_reports_not_observable_identity_capture(self) -> None:
        path = self.tmp / "not-observable.env"
        path.write_text("STATUS=NOT_FOUND\nLISTENER_READY=UNKNOWN\n", encoding="utf-8")
        out = self.run_observer("--identity-file", str(path))
        self.assertEqual(out["CONFLICT_DETECTION_SUFFICIENT"], "false")
        self.assertEqual(out["LISTENER_PROCESS_GENERATION_OBSERVABLE"], "false")
        self.assertEqual(out["LISTENER_SOCKET_IDENTITY_OBSERVABLE"], "false")
        self.assertIn("listener process generation", out["MISSING_CAPABILITY"])


if __name__ == "__main__":
    unittest.main()
