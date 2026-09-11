#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
PINNED = ROOT / "custom_components" / "comelit" / "native" / "comelit-media"
REBUILT = ROOT / ".p116-evidence" / "bin" / "rebuilt-historical-source.bin"
PINNED_SHA256 = "91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7"
REBUILT_SHA256 = "f17ad2d6efbe002335a658c075da84677ced44246d556afe80953a8f59129841"
EXPECTED_NEEDED = [
    "libc.musl-x86_64.so.1",
    "libglib-2.0.so.0",
    "libgobject-2.0.so.0",
    "libnice.so.10",
]
RUNTIME_SECTIONS = (
    ".interp",
    ".gnu.hash",
    ".dynsym",
    ".dynstr",
    ".rela.dyn",
    ".rela.plt",
    ".init",
    ".plt",
    ".plt.got",
    ".text",
    ".fini",
    ".rodata",
    ".eh_frame_hdr",
    ".eh_frame",
    ".init_array",
    ".fini_array",
    ".data.rel.ro",
    ".dynamic",
    ".got",
    ".data",
    ".bss",
)
DEBUG_SECTIONS = {
    ".debug_aranges",
    ".debug_info",
    ".debug_abbrev",
    ".debug_line",
    ".debug_frame",
    ".debug_str",
    ".debug_line_str",
    ".debug_loclists",
    ".debug_rnglists",
}


@dataclass(frozen=True)
class Section:
    name: str
    kind: str
    address: int
    offset: int
    size: int
    flags: str
    sha256: str


def _run(*args: str) -> str:
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sections(path: Path) -> dict[str, Section]:
    data = path.read_bytes()
    sections: dict[str, Section] = {}
    for line in _run("readelf", "-SW", str(path)).splitlines():
        match = re.match(
            r"^\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-fA-F]+)\s+"
            r"([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]+\s*(\S*)",
            line,
        )
        if not match:
            continue
        name, kind, address, offset, size, flags = match.groups()
        offset_int = int(offset, 16)
        size_int = int(size, 16)
        if kind == "NOBITS":
            digest = "NOBITS"
        else:
            digest = hashlib.sha256(data[offset_int : offset_int + size_int]).hexdigest()
        sections[name] = Section(
            name=name,
            kind=kind,
            address=int(address, 16),
            offset=offset_int,
            size=size_int,
            flags=flags,
            sha256=digest,
        )
    return sections


def _build_id(path: Path) -> str:
    match = re.search(r"Build ID: ([0-9a-f]+)", _run("readelf", "-n", str(path)))
    assert match is not None
    return match.group(1)


def _interpreter(path: Path) -> str:
    match = re.search(r"Requesting program interpreter: ([^\]]+)\]", _run("readelf", "-l", str(path)))
    assert match is not None
    return match.group(1)


def _needed(path: Path) -> list[str]:
    return sorted(re.findall(r"Shared library: \[([^\]]+)\]", _run("readelf", "-d", str(path))))


def _relocation_count(path: Path) -> int:
    return sum(1 for line in _run("readelf", "-r", str(path)).splitlines() if re.match(r"^[0-9a-fA-F]", line.strip()))


def _symbol_count(path: Path, dynamic: bool = False) -> int:
    args = ["nm"]
    if dynamic:
        args.append("-D")
    result = subprocess.run(
        [*args, str(path)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def _comment(path: Path) -> str:
    text = _run("readelf", "-p", ".comment", str(path))
    match = re.search(r"\]\s+(.+)$", text, re.MULTILINE)
    assert match is not None
    return match.group(1)


def _program_headers(path: Path) -> list[str]:
    lines = []
    capture = False
    for line in _run("readelf", "-l", str(path)).splitlines():
        if line.startswith("Program Headers:"):
            capture = True
        elif line.startswith(" Section to Segment mapping:"):
            break
        elif capture:
            lines.append(line.rstrip())
    return lines


class P116ProvenanceBinaryAnalysisTests(unittest.TestCase):
    def test_rebuilt_historical_binary_mismatch_is_non_runtime_metadata(self) -> None:
        self.assertTrue(PINNED.is_file())
        self.assertTrue(REBUILT.is_file())
        self.assertEqual(_sha256(PINNED), PINNED_SHA256)
        self.assertEqual(_sha256(REBUILT), REBUILT_SHA256)
        self.assertEqual(PINNED.stat().st_size - REBUILT.stat().st_size, 32)

        pinned_sections = _sections(PINNED)
        rebuilt_sections = _sections(REBUILT)
        self.assertEqual(pinned_sections.keys(), rebuilt_sections.keys())
        self.assertEqual(_program_headers(PINNED), _program_headers(REBUILT))
        self.assertEqual(_interpreter(PINNED), "/lib/ld-musl-x86_64.so.1")
        self.assertEqual(_interpreter(PINNED), _interpreter(REBUILT))
        self.assertEqual(_needed(PINNED), EXPECTED_NEEDED)
        self.assertEqual(_needed(PINNED), _needed(REBUILT))
        self.assertEqual(_comment(PINNED), "GCC: (Alpine 15.2.0) 15.2.0")
        self.assertEqual(_comment(PINNED), _comment(REBUILT))
        self.assertNotEqual(_build_id(PINNED), _build_id(REBUILT))
        self.assertEqual(_symbol_count(PINNED), 340)
        self.assertEqual(_symbol_count(PINNED), _symbol_count(REBUILT))
        self.assertEqual(_symbol_count(PINNED, dynamic=True), 104)
        self.assertEqual(_symbol_count(PINNED, dynamic=True), _symbol_count(REBUILT, dynamic=True))
        self.assertEqual(_relocation_count(PINNED), 107)
        self.assertEqual(_relocation_count(PINNED), _relocation_count(REBUILT))

        for name in RUNTIME_SECTIONS:
            with self.subTest(section=name):
                pinned = pinned_sections[name]
                rebuilt = rebuilt_sections[name]
                self.assertEqual(pinned.kind, rebuilt.kind)
                self.assertEqual(pinned.address, rebuilt.address)
                self.assertEqual(pinned.offset, rebuilt.offset)
                self.assertEqual(pinned.size, rebuilt.size)
                self.assertEqual(pinned.flags, rebuilt.flags)
                self.assertEqual(pinned.sha256, rebuilt.sha256)

        self.assertEqual(pinned_sections[".debug_line"].size, 0x6C99)
        self.assertEqual(rebuilt_sections[".debug_line"].size, 0x6C95)
        self.assertEqual(pinned_sections[".debug_line_str"].size, 0x2DB)
        self.assertEqual(rebuilt_sections[".debug_line_str"].size, 0x2BD)
        self.assertLess(rebuilt_sections[".symtab"].offset, pinned_sections[".symtab"].offset)
        self.assertLess(rebuilt_sections[".strtab"].offset, pinned_sections[".strtab"].offset)
        self.assertLess(rebuilt_sections[".shstrtab"].offset, pinned_sections[".shstrtab"].offset)
        self.assertEqual(pinned_sections[".comment"].sha256, rebuilt_sections[".comment"].sha256)

        differing_non_runtime = {
            name
            for name, pinned in pinned_sections.items()
            if pinned.sha256 != rebuilt_sections[name].sha256
            or pinned.offset != rebuilt_sections[name].offset
            or pinned.size != rebuilt_sections[name].size
        } - {".note.gnu.build-id", ".symtab", ".strtab", ".shstrtab"} - DEBUG_SECTIONS
        self.assertEqual(differing_non_runtime, set())


if __name__ == "__main__":
    unittest.main()
