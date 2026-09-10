#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import re
import struct
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SAFETY_ROOT = ROOT / "safety-poc"
MEDIA_DIR = SAFETY_ROOT / "research" / "media" / "v1"
TRANSPORT = ROOT / "custom_components" / "comelit" / "media_transport.py"
BINARY = ROOT / "custom_components" / "comelit" / "native" / "comelit-media"
NATIVE_LIB = ROOT / "custom_components" / "comelit" / "native" / "lib"
SOURCE = SAFETY_ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
EXPECTED_MUSL_SHA256 = "ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade"
EXPECTED_RUN3_GLIBC_SHA256 = "94063498a35a886dc4cb735c3e629a5097b965224cb3354192723d30e70c16ac"
EXPECTED_SOURCE_SHA256 = "262858014942a652524675bf94cb7327f883fa82516a2b28c577bcd13d15a99d"
EXPECTED_INTERPRETER = "/lib/ld-musl-x86_64.so.1"
EXPECTED_NEEDED = (
    "libc.musl-x86_64.so.1",
    "libglib-2.0.so.0",
    "libgobject-2.0.so.0",
    "libnice.so.10",
)


class Elf64:
    PT_LOAD = 1
    PT_DYNAMIC = 2
    PT_INTERP = 3
    DT_NEEDED = 1
    DT_STRTAB = 5
    DT_NULL = 0

    def __init__(self, blob: bytes) -> None:
        self.blob = blob
        self._parse_header()
        self.program_headers = self._program_headers()

    def _parse_header(self) -> None:
        self.assert_elf64_little_endian()
        self.e_phoff = struct.unpack_from("<Q", self.blob, 32)[0]
        self.e_phentsize = struct.unpack_from("<H", self.blob, 54)[0]
        self.e_phnum = struct.unpack_from("<H", self.blob, 56)[0]

    def assert_elf64_little_endian(self) -> None:
        if self.blob[:4] != b"\x7fELF":
            raise AssertionError("not an ELF file")
        if self.blob[4] != 2:
            raise AssertionError("not ELF64")
        if self.blob[5] != 1:
            raise AssertionError("not little-endian ELF")

    def _program_headers(self) -> list[dict[str, int]]:
        headers: list[dict[str, int]] = []
        for index in range(self.e_phnum):
            offset = self.e_phoff + index * self.e_phentsize
            (
                p_type,
                _p_flags,
                p_offset,
                p_vaddr,
                _p_paddr,
                p_filesz,
                _p_memsz,
                _p_align,
            ) = struct.unpack_from("<IIQQQQQQ", self.blob, offset)
            headers.append(
                {
                    "type": p_type,
                    "offset": p_offset,
                    "vaddr": p_vaddr,
                    "filesz": p_filesz,
                }
            )
        return headers

    def _vaddr_to_offset(self, vaddr: int) -> int:
        for header in self.program_headers:
            if header["type"] != self.PT_LOAD:
                continue
            start = header["vaddr"]
            end = start + header["filesz"]
            if start <= vaddr < end:
                return header["offset"] + (vaddr - start)
        raise AssertionError(f"ELF virtual address not mapped: {vaddr:#x}")

    def _cstring(self, offset: int) -> str:
        end = self.blob.index(b"\0", offset)
        return self.blob[offset:end].decode("ascii")

    def interpreter(self) -> str:
        interpreters = [h for h in self.program_headers if h["type"] == self.PT_INTERP]
        if len(interpreters) != 1:
            raise AssertionError(f"expected one PT_INTERP, found {len(interpreters)}")
        header = interpreters[0]
        raw = self.blob[header["offset"] : header["offset"] + header["filesz"]]
        return raw.rstrip(b"\0").decode("ascii")

    def needed(self) -> tuple[str, ...]:
        dynamic = [h for h in self.program_headers if h["type"] == self.PT_DYNAMIC]
        if len(dynamic) != 1:
            raise AssertionError(f"expected one PT_DYNAMIC, found {len(dynamic)}")
        entries: list[tuple[int, int]] = []
        header = dynamic[0]
        for offset in range(header["offset"], header["offset"] + header["filesz"], 16):
            tag, value = struct.unpack_from("<QQ", self.blob, offset)
            if tag == self.DT_NULL:
                break
            entries.append((tag, value))
        strtab = next(value for tag, value in entries if tag == self.DT_STRTAB)
        strtab_offset = self._vaddr_to_offset(strtab)
        return tuple(
            self._cstring(strtab_offset + value)
            for tag, value in entries
            if tag == self.DT_NEEDED
        )


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _transport_sha_pin(source: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "MEDIA_NATIVE_BINARY_SHA256" for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        if isinstance(value, str):
            return value
    raise AssertionError("MEDIA_NATIVE_BINARY_SHA256 assignment not found")


def _marker_value_pattern(source: str) -> re.Pattern[str]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name)
            and target.id == "_MEDIA_NATIVE_MARKER_SAFE_VALUE_RE"
            for target in node.targets
        ):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            break
        return re.compile(ast.literal_eval(call.args[0]))
    raise AssertionError("_MEDIA_NATIVE_MARKER_SAFE_VALUE_RE assignment not found")


class P107MuslPackageProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.transport_source = TRANSPORT.read_text(encoding="utf-8")
        cls.transport_tree = ast.parse(cls.transport_source)
        cls.binary_blob = BINARY.read_bytes()
        cls.elf = Elf64(cls.binary_blob)

    def test_packaged_binary_sha256_matches_transport_pin_and_offline_musl_artifact(self) -> None:
        actual = _sha256_bytes(self.binary_blob)
        self.assertEqual(actual, EXPECTED_MUSL_SHA256)
        self.assertEqual(_transport_sha_pin(self.transport_source), EXPECTED_MUSL_SHA256)
        self.assertNotEqual(actual, EXPECTED_RUN3_GLIBC_SHA256)

    def test_packaged_binary_is_musl_elf_with_exact_needed_set(self) -> None:
        interpreter = self.elf.interpreter()
        needed = self.elf.needed()
        self.assertEqual(interpreter, EXPECTED_INTERPRETER)
        self.assertEqual(tuple(sorted(needed)), EXPECTED_NEEDED)
        self.assertIn("libc.musl-x86_64.so.1", needed)
        self.assertNotIn("libc.so.6", needed)
        self.assertNotIn("ld-linux", interpreter)

    def test_non_musl_needed_sonames_are_packaged_in_native_lib(self) -> None:
        needed = set(self.elf.needed())
        self.assertEqual(needed, set(EXPECTED_NEEDED))
        for soname in sorted(needed - {"libc.musl-x86_64.so.1"}):
            self.assertTrue((NATIVE_LIB / soname).is_file(), soname)

    def test_packaged_binary_contains_required_p106_p80_markers(self) -> None:
        markers = (
            b"P80_DEVICE_ACK_000A_OBSERVED=PASS",
            b"P80_DEVICE_ACK_001A_OBSERVED=PASS",
            b"P80_POST_001A_ACK_GATE=PASS",
            b"P80_PREACTIVE_MEDIA_DEMUX=PASS",
            b"P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS",
            b"P80_MEDIA_ACTIVE=true",
            b"P80_VIDEO_RTP_FORWARDING=PASS",
            b"P80_AUDIO_RTP_FORWARDING=PASS",
            b"PSEUDOTCP_NOTIFY_PACKET_CLASS=%s",
            b"PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED=%s",
            b"PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED=%s",
            b"PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true",
        )
        for marker in markers:
            self.assertIn(marker, self.binary_blob)

    def test_generated_source_provenance_matches_p106_transform_digest(self) -> None:
        sys.path.insert(0, str(MEDIA_DIR))
        from entrance_p106_teardown_state_classification_transform import transform

        # Deterministic command:
        # PYTHONPATH=safety-poc/research/media/v1 python3 -c
        # 'from pathlib import Path; import hashlib; from
        # entrance_p106_teardown_state_classification_transform import transform;
        # print(hashlib.sha256(transform(Path("safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c").read_text(encoding="utf-8")).encode("utf-8")).hexdigest())'
        candidate = transform(SOURCE.read_text(encoding="utf-8")).encode("utf-8")
        self.assertEqual(hashlib.sha256(candidate).hexdigest(), EXPECTED_SOURCE_SHA256)

    def test_p106_terminal_classes_are_diagnostic_allowlist_only(self) -> None:
        pattern = _marker_value_pattern(self.transport_source)
        self.assertIsNotNone(pattern.fullmatch("EXPECTED_TERMINAL_SHUTDOWN"))
        self.assertIsNotNone(pattern.fullmatch("FATAL"))
        self.assertIsNone(pattern.fullmatch("UNBOUNDED_ARBITRARY_VALUE"))
        self.assertEqual(self.transport_source.count("EXPECTED_TERMINAL_SHUTDOWN"), 1)
        self.assertEqual(self.transport_source.count("FATAL"), 1)
        for node in ast.walk(self.transport_tree):
            if not isinstance(node, ast.If):
                continue
            condition = ast.get_source_segment(self.transport_source, node.test) or ""
            self.assertNotIn("EXPECTED_TERMINAL_SHUTDOWN", condition)
            self.assertNotIn("FATAL", condition)

    def test_media_lifecycle_invariants_remain_static(self) -> None:
        source = self.transport_source
        self.assertEqual(source.count("async_negotiate_p2p("), 1)
        self.assertEqual(source.count("asyncio.create_subprocess_exec("), 1)
        self.assertIn('line == "P80_MEDIA_ACTIVE=true"', source)
        self.assertIn('line == "P80_VIDEO_RTP_FORWARDING=PASS"', source)
        self.assertIn('line == "P80_AUDIO_RTP_FORWARDING=PASS"', source)
        for forbidden in (
            "for attempt",
            "force_refresh=True",
            "async_open_door",
            "create_door_message",
            "homeassistant.restart",
            "systemctl",
            'panel == "gate"',
            'panel != "entrance"',
            "LEN=24",
        ):
            if forbidden == 'panel != "entrance"':
                self.assertIn(forbidden, source)
            else:
                self.assertNotIn(forbidden, source)

    def test_native_gate_still_hashes_before_launch(self) -> None:
        gate_start = self.transport_source.index("def _native_gate() -> None:")
        gate_end = self.transport_source.index(
            "\n\n\nclass ComelitEntranceMediaTransport", gate_start
        )
        gate = self.transport_source[gate_start:gate_end]
        self.assertIn("actual_sha256 = _sha256_file(_MEDIA_NATIVE_BINARY)", gate)
        self.assertIn("media_native_binary_sha256_mismatch", gate)
        cycle_start = self.transport_source.index("async def _async_run_cycle(self) -> None:")
        cycle = self.transport_source[cycle_start:]
        self.assertLess(
            cycle.index("await self._hass.async_add_executor_job(_native_gate)"),
            cycle.index("asyncio.create_subprocess_exec("),
        )


if __name__ == "__main__":
    unittest.main()
