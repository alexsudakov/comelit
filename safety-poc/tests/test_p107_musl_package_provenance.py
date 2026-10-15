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
P80_BUILDER = MEDIA_DIR / "ct120_build_p80_haos_media_helper.sh"
# p116_media_telemetry_build_meta.txt is the frozen R30E-era provenance
# record; R65 promoted a binary over it (bounded periodic media refresh) and
# the settle-candidate round (ENTRANCE_SIGNAL_SETTLE_MS 4000 -> 1000) then
# promoted the current one over R65 in
# p117_settle1000_production_media_build_meta.txt (frozen from now on) and
# p116_r65_production_media_build_meta.txt is the frozen record of the
# superseded R65 pair.
#
# P125 ring-id probe has a completed observability-only native promotion. The
# packaged binary is verified against the promoted artifact recorded here, not
# against the current HEAD P116/P122 source identity.
BUILD_META = MEDIA_DIR / "p125_ringid_probe_media_build_meta.txt"
P125_REBUILD_RECORD = MEDIA_DIR / "p125_ringid_probe_media_rebuild_record.txt"
FROZEN_P124_BUILD_META = MEDIA_DIR / "p124_ctpp_refresh15_production_media_build_meta.txt"
FROZEN_P123_BUILD_META = (
    MEDIA_DIR / "p123_manual_p122_door_repeat_production_media_build_meta.txt"
)
FROZEN_P122_ACTIVE_BUILD_META = (
    MEDIA_DIR / "p122_active_media_eligibility_production_media_build_meta.txt"
)
FROZEN_P122_ON_DEMAND_BUILD_META = (
    MEDIA_DIR / "p122_on_demand_media_door_production_media_build_meta.txt"
)
FROZEN_P121_BUILD_META = MEDIA_DIR / "p121_gather_initial_timeout_production_media_build_meta.txt"
FROZEN_P119_BUILD_META = (
    MEDIA_DIR / "p119_remote_sdp_l1_gather_diag_production_media_build_meta.txt"
)
# The P119 pair is now the superseded record; keep it as literal values so it keeps
# describing the artifact P119 actually built, not whatever HEAD pins currently say.
SUPERSEDED_P121_BINARY_SHA256 = "9347a973b012d5ca86b406642a5fcd9b86ce44201d0b5144073005ca72ce7712"
SUPERSEDED_P121_SOURCE_SHA256 = "07468cd74027d02d5f002c1cc63558f68526cf06b9694c5afe94579ea68f9e74"
SUPERSEDED_P119_BINARY_SHA256 = "095051f42b7e6393c48fce51eaef73665e722fc852f263beed1b5c433308b0e0"
SUPERSEDED_P119_SOURCE_SHA256 = "2f8137e988437c779a0f3bb1c9904c81cbe2d13641efa2e6a070054116dd43ed"
SUPERSEDED_P122_ACTIVE_BINARY_SHA256 = "5811415a95bbeb687e7f91d5a1ed70c67473086ddefa4bfb602eba2798ad0573"
SUPERSEDED_P122_ON_DEMAND_BINARY_SHA256 = "a3c95f3ec8c5c00963946c8ff550760fadd792a314bb72692e4281da35a5a6a5"
SUPERSEDED_P122_ACTIVE_SOURCE_SHA256 = "fa5f3fef61b6673718d677e150770c2af6fe2c752d0756034c9ad5e1864a384c"
SUPERSEDED_P122_ON_DEMAND_SOURCE_SHA256 = "fd375a37e427e680db60984f6d74807e56892a1a042a168032a6dfa42411eff5"
SUPERSEDED_P123_BINARY_SHA256 = "04bb610e02562fb4a301813001616308dd22dbabe5507b397a5abdc7194075b2"
SUPERSEDED_P123_SOURCE_SHA256 = "ec39399ade72cb4800131d5a0995e0053a3f9af22560fd40894af057994d6d47"
SUPERSEDED_P124_BINARY_SHA256 = "83b29ef07be224ffb703a21f50050b1ed5e7eec3e24f185cbfde4c79c111515a"
SUPERSEDED_P124_SOURCE_SHA256 = "92e12f5a27dd728231e073076429863cdc059825819f4f600d5d3dd50138ca26"
FROZEN_P117_BUILD_META = MEDIA_DIR / "p117_settle1000_production_media_build_meta.txt"
FROZEN_R65_BUILD_META = MEDIA_DIR / "p116_r65_production_media_build_meta.txt"
PRE_R65_BUILD_META = MEDIA_DIR / "p116_media_telemetry_build_meta.txt"
EXPECTED_MUSL_SHA256 = "2a10b69e6c7e0565fa088b509904df1779478f0227fbbb8f6d4ba12034d8f045"
EXPECTED_RUN3_GLIBC_SHA256 = "94063498a35a886dc4cb735c3e629a5097b965224cb3354192723d30e70c16ac"
# PACKAGED_NATIVE_SOURCE_SHA256 is the source identity actually baked into the
# packaged EXPECTED_MUSL_SHA256 binary. HEAD_P116_SOURCE_SHA256 is what
# regenerating HEAD's canonical P116/P122 candidate produces without the
# observability overlay.
PACKAGED_NATIVE_SOURCE_SHA256 = "4bfdf264fbd74c5796d2386d835f0beeea15d23f8c3b1ea460323b7930b741a7"
HEAD_P116_SOURCE_SHA256 = "92e12f5a27dd728231e073076429863cdc059825819f4f600d5d3dd50138ca26"
# The P117 pair is now a historical record: these must stay literal values so
# they keep describing the artifact P117 actually built, not the current pins.
SUPERSEDED_P117_BINARY_SHA256 = "ff16db0d809135cf5cdf6be4bfe8133fd77b3f41871b6c8f46eea765064537fb"
SUPERSEDED_P117_SOURCE_SHA256 = "4448e8368bd6275a2cd398c35ef171d012f315d2bb5bd05daf2e33a13d4c0001"
SUPERSEDED_R65_BINARY_SHA256 = "76218861c72e9a2b87283df6c5c7e0b03a4d7fb11bee4364f59be1513acd6129"
SUPERSEDED_R65_SOURCE_SHA256 = "4fc6188c6231b94682205973b6a6f628ca005e8b7c3a04efbd8056c5a608c58c"
PRE_R65_PACKAGED_BINARY_SHA256 = "a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8"
PRE_R65_PACKAGED_SOURCE_SHA256 = "1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2"
PRE_R30E_PACKAGED_BINARY_SHA256 = "35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622"
PRE_R30E_PACKAGED_SOURCE_SHA256 = "93756730fd088b9227f37c4e0e3edbd18ac30c110db03b75bcc63f1c93952e66"
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


def _metadata(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


class P107MuslPackageProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.transport_source = TRANSPORT.read_text(encoding="utf-8")
        cls.transport_tree = ast.parse(cls.transport_source)
        cls.binary_blob = BINARY.read_bytes()
        cls.elf = Elf64(cls.binary_blob)

    def test_packaged_binary_sha256_matches_transport_pin_and_offline_musl_artifact(self) -> None:
        actual = _sha256_bytes(self.binary_blob)
        meta = _metadata(BUILD_META)
        frozen_p124_meta = _metadata(FROZEN_P124_BUILD_META)
        frozen_p123_meta = _metadata(FROZEN_P123_BUILD_META)
        frozen_p117_meta = _metadata(FROZEN_P117_BUILD_META)
        frozen_r65_meta = _metadata(FROZEN_R65_BUILD_META)
        pre_r65_meta = _metadata(PRE_R65_BUILD_META)
        self.assertEqual(actual, EXPECTED_MUSL_SHA256)
        self.assertEqual(_transport_sha_pin(self.transport_source), EXPECTED_MUSL_SHA256)
        frozen_p119_meta = _metadata(FROZEN_P119_BUILD_META)
        frozen_p122_active_meta = _metadata(FROZEN_P122_ACTIVE_BUILD_META)
        frozen_p122_on_demand_meta = _metadata(FROZEN_P122_ON_DEMAND_BUILD_META)
        self.assertEqual(meta["phase"], "P125_RINGID_PROBE_MEDIA_OBSERVABILITY_ONLY")
        self.assertEqual(meta["observability_only"], "true")
        self.assertEqual(
            meta["reproducible_build_record"],
            "safety-poc/research/media/v1/p125_ringid_probe_media_rebuild_record.txt",
        )
        self.assertTrue(P125_REBUILD_RECORD.is_file())
        rebuild_record = _metadata(P125_REBUILD_RECORD)
        self.assertEqual(
            rebuild_record["record_type"],
            "reproducible_ct120_media_build_record",
        )
        self._assert_p125_rebuild_record_is_honest(rebuild_record, meta)
        self.assertEqual(meta["BODY_32_35_SEMANTICS_PROVEN"], "false")
        self.assertEqual(meta["GENERATED_SOURCE_SHA256"], PACKAGED_NATIVE_SOURCE_SHA256)
        verified_promoted_p125_artifact_sha = meta["NATIVE_BINARY_SHA256"]
        self.assertRegex(verified_promoted_p125_artifact_sha, r"^[0-9a-f]{64}$")
        self.assertEqual(actual, verified_promoted_p125_artifact_sha)
        self.assertEqual(verified_promoted_p125_artifact_sha, EXPECTED_MUSL_SHA256)
        self.assertEqual(meta["build_a_sha256"], verified_promoted_p125_artifact_sha)
        self.assertEqual(meta["build_b_sha256"], verified_promoted_p125_artifact_sha)
        self.assertEqual(meta["reproducible_binary_cmp_gate"], "PASS")
        self.assertEqual(meta["CONTROL_BUILD_REPRODUCES_CURRENT_BINARY"], "true")
        self.assertEqual(frozen_p119_meta["NATIVE_BINARY_SHA256"], SUPERSEDED_P119_BINARY_SHA256)
        self.assertEqual(
            frozen_p119_meta["GENERATED_SOURCE_SHA256"], SUPERSEDED_P119_SOURCE_SHA256
        )
        self.assertEqual(meta["NATIVE_BINARY_SHA256"], EXPECTED_MUSL_SHA256)
        self.assertEqual(
            meta["superseded_native_binary_sha256"], SUPERSEDED_P124_BINARY_SHA256
        )
        self.assertEqual(
            meta["superseded_generated_source_sha256"],
            SUPERSEDED_P124_SOURCE_SHA256,
        )
        self.assertEqual(
            meta["replaced_native_binary_sha256"],
            "99ec3f5b044277bd6573fb95580f2198493399fee35c85122fbb2386c654cbc6",
        )
        self.assertEqual(
            meta["replaced_generated_source_sha256"],
            "a66bded0e618f3308204acb8514f33054036c9eac585daa5cc1e28316572b6ef",
        )
        # The replaced_* lineage pins live in the meta file (asserted above);
        # the build record carries only what the builder itself emits.
        self.assertNotIn("replaced_native_binary_sha256", rebuild_record)
        self.assertNotIn("replaced_generated_source_sha256", rebuild_record)
        self.assertEqual(frozen_p124_meta["NATIVE_BINARY_SHA256"], SUPERSEDED_P124_BINARY_SHA256)
        self.assertEqual(
            frozen_p124_meta["GENERATED_SOURCE_SHA256"], SUPERSEDED_P124_SOURCE_SHA256
        )
        self.assertEqual(
            frozen_p123_meta["NATIVE_BINARY_SHA256"], SUPERSEDED_P123_BINARY_SHA256
        )
        self.assertEqual(
            frozen_p123_meta["GENERATED_SOURCE_SHA256"], SUPERSEDED_P123_SOURCE_SHA256
        )
        self.assertEqual(
            frozen_p123_meta["superseded_native_binary_sha256"],
            SUPERSEDED_P122_ACTIVE_BINARY_SHA256,
        )
        self.assertEqual(
            frozen_p123_meta["superseded_generated_source_sha256"],
            SUPERSEDED_P122_ACTIVE_SOURCE_SHA256,
        )
        self.assertEqual(
            frozen_p122_on_demand_meta["NATIVE_BINARY_SHA256"],
            SUPERSEDED_P122_ON_DEMAND_BINARY_SHA256,
        )
        self.assertEqual(
            frozen_p122_on_demand_meta["GENERATED_SOURCE_SHA256"],
            SUPERSEDED_P122_ON_DEMAND_SOURCE_SHA256,
        )
        self.assertEqual(
            frozen_p122_active_meta["NATIVE_BINARY_SHA256"],
            SUPERSEDED_P122_ACTIVE_BINARY_SHA256,
        )
        self.assertEqual(
            frozen_p122_active_meta["GENERATED_SOURCE_SHA256"],
            SUPERSEDED_P122_ACTIVE_SOURCE_SHA256,
        )
        self.assertEqual(
            frozen_p122_active_meta["superseded_native_binary_sha256"],
            SUPERSEDED_P122_ON_DEMAND_BINARY_SHA256,
        )
        self.assertEqual(
            frozen_p122_active_meta["superseded_generated_source_sha256"],
            SUPERSEDED_P122_ON_DEMAND_SOURCE_SHA256,
        )
        self.assertEqual(
            frozen_p119_meta["superseded_native_binary_sha256"], SUPERSEDED_P117_BINARY_SHA256
        )
        # The frozen P117 record documents the artifact it actually built and
        # verified with two independent builds; it must not be rewritten.
        self.assertEqual(frozen_p117_meta["NATIVE_BINARY_SHA256"], SUPERSEDED_P117_BINARY_SHA256)
        self.assertEqual(frozen_p117_meta["build_a_sha256"], SUPERSEDED_P117_BINARY_SHA256)
        self.assertEqual(frozen_p117_meta["build_b_sha256"], SUPERSEDED_P117_BINARY_SHA256)
        self.assertEqual(frozen_p117_meta["superseded_native_binary_sha256"], SUPERSEDED_R65_BINARY_SHA256)
        # The frozen R65 record documents the artifact it built -- exactly the
        # pair the P117 round superseded -- and must not be rewritten.
        self.assertEqual(frozen_r65_meta["NATIVE_BINARY_SHA256"], SUPERSEDED_R65_BINARY_SHA256)
        self.assertEqual(frozen_r65_meta["build_a_sha256"], SUPERSEDED_R65_BINARY_SHA256)
        self.assertEqual(frozen_r65_meta["build_b_sha256"], SUPERSEDED_R65_BINARY_SHA256)
        self.assertEqual(frozen_r65_meta["superseded_native_binary_sha256"], PRE_R65_PACKAGED_BINARY_SHA256)
        self.assertNotEqual(actual, SUPERSEDED_R65_BINARY_SHA256)
        # pre_r65_meta (the frozen R30E-era record) still documents the
        # binary it shipped, unmodified, so it must equal the superseded pin.
        self.assertEqual(pre_r65_meta["NATIVE_BINARY_SHA256"], PRE_R65_PACKAGED_BINARY_SHA256)
        self.assertEqual(pre_r65_meta["historical_pre_r30e_native_binary_sha256"], PRE_R30E_PACKAGED_BINARY_SHA256)
        self.assertNotEqual(actual, PRE_R65_PACKAGED_BINARY_SHA256)
        self.assertNotEqual(actual, PRE_R30E_PACKAGED_BINARY_SHA256)
        self.assertNotEqual(actual, EXPECTED_RUN3_GLIBC_SHA256)

    def _assert_p125_rebuild_record_is_honest(
        self, record: dict[str, str], meta: dict[str, str]
    ) -> None:
        builder_path = "safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh"
        gate_keys = (
            "P80_HAOS_MEDIA_BUILD",
            "PROFILE_SOURCE_GATE",
            "PROFILE_BINARY_GATE",
            "P80_BINARY_MARKER_GATE",
            "MUSL_INTERPRETER_GATE",
            "NO_GLIBC_DEPENDENCY",
            "NO_NEW_RUNTIME_DEPENDENCY",
            "LIB_IDENTICAL",
            "P80_BUILD_EXPECTED_SOURCE_SHA_GATE",
        )
        self.assertEqual(record["phase"], meta["phase"])
        self.assertEqual(record["builder"], meta["builder"])
        self.assertEqual(record["transform"], meta["P80_BUILD_TRANSFORM"])
        self.assertEqual(record["P80_BUILD_PROFILE"], meta["P80_BUILD_PROFILE"])
        self.assertEqual(record["P80_BUILD_INCLUDE_P116"], meta["P80_BUILD_INCLUDE_P116"])
        self.assertEqual(record["hardcoded_gate_results"], "false")
        self.assertEqual(record["candidate_executed"], "false")
        self.assertEqual(record["production_deploy_performed"], "false")
        status = record["record_status"]
        if status == "PENDING_BUILDER_REGENERATION":
            # A hand-written placeholder must not claim builder provenance
            # or carry any measured value / gate result.
            self.assertNotEqual(record["record_generated_by"], builder_path)
            self.assertEqual(record["builder_emitted"], "false")
            self.assertEqual(record["measured_values_present"], "false")
            self.assertNotEqual(record["gate_results_source"], "builder_executed_gates")
            for key in gate_keys + (
                "native_binary_sha256",
                "generated_source_sha256",
                "build_repo_head",
                "elf_build_id",
                "build_a_sha256",
                "build_b_sha256",
                "reproducible_binary_cmp_gate",
            ):
                self.assertNotIn(key, record)
            self.assertEqual(
                record["regeneration_record_phase"], meta["phase"]
            )
            self.assertEqual(
                record["regeneration_expected_source_sha_pin"],
                meta["GENERATED_SOURCE_SHA256"],
            )
            self.assertEqual(
                record["regeneration_expected_native_binary_sha_pin"],
                EXPECTED_MUSL_SHA256,
            )
            return
        self.assertEqual(status, "BUILDER_EMITTED")
        # Builder-emitted: every field below is written by the builder from
        # the gate variables it actually executed.
        self.assertEqual(record["record_generated_by"], builder_path)
        self.assertEqual(record["gate_results_source"], "builder_executed_gates")
        self.assertRegex(record["build_repo_head"], r"^[0-9a-f]{40}$")
        self.assertEqual(record["generated_source_sha256"], meta["GENERATED_SOURCE_SHA256"])
        self.assertEqual(record["native_binary_sha256"], EXPECTED_MUSL_SHA256)
        self.assertEqual(record["native_binary_sha256"], meta["NATIVE_BINARY_SHA256"])
        self.assertEqual(record["P80_BUILD_EXPECTED_SOURCE_SHA"], meta["GENERATED_SOURCE_SHA256"])
        self.assertEqual(record["P80_BUILD_EXPECTED_SOURCE_SHA_GATE"], "PASS")
        self.assertEqual(record["elf_build_id"], meta["elf_build_id"])
        self.assertEqual(record["interpreter"], meta["interpreter"])
        self.assertEqual(record["needed_sorted"], meta["needed_sorted"])
        self.assertEqual(record["P80_HAOS_MEDIA_BUILD"], "PASS")
        self.assertEqual(record["PROFILE_SOURCE_GATE"], meta["PROFILE_SOURCE_GATE"])
        self.assertEqual(record["PROFILE_BINARY_GATE"], meta["PROFILE_BINARY_GATE"])
        self.assertEqual(record["P80_BINARY_MARKER_GATE"], meta["P80_BINARY_MARKER_GATE"])
        self.assertEqual(record["MUSL_INTERPRETER_GATE"], meta["P80_INTERPRETER_GATE"])
        self.assertEqual(record["NO_GLIBC_DEPENDENCY"], meta["NO_GLIBC_DEPENDENCY"])
        self.assertEqual(record["NO_NEW_RUNTIME_DEPENDENCY"], meta["NO_NEW_RUNTIME_DEPENDENCY"])
        self.assertEqual(record["LIB_IDENTICAL"], meta["LIB_IDENTICAL"])

    def test_p125_rebuild_record_is_builder_emitted_not_a_placeholder(self) -> None:
        # The hand-written placeholder this guard used to reject has been
        # replaced by the real builder-emitted record. Assert the emitted state
        # directly instead of skipping, so the coverage is not silently dropped
        # and the suite's skip budget is not inflated by a now-obsolete guard.
        record = _metadata(P125_REBUILD_RECORD)
        self.assertEqual(record["record_status"], "BUILDER_EMITTED")
        self.assertEqual(
            record["record_generated_by"],
            "safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh",
        )
        self.assertEqual(record["gate_results_source"], "builder_executed_gates")
        self.assertEqual(record["hardcoded_gate_results"], "false")
        record_text = P125_REBUILD_RECORD.read_text(encoding="utf-8")
        self.assertIn("gate_results_source=builder_executed_gates", record_text)
        self.assertNotIn("hand_written_placeholder_not_builder_output", record_text)
        self.assertNotIn("PENDING_BUILDER_REGENERATION", record_text)
        self.assertNotIn("repo_head_at_build", _metadata(BUILD_META))

    def test_media_builder_can_emit_machine_verifiable_rebuild_record(self) -> None:
        builder = P80_BUILDER.read_text(encoding="utf-8")
        self.assertIn("P80_BUILD_RECORD_OUTPUT=${P80_BUILD_RECORD_OUTPUT:-}", builder)
        self.assertIn('echo "record_generated_by=safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh"', builder)
        self.assertIn('echo "record_status=BUILDER_EMITTED"', builder)
        self.assertIn('echo "phase=$P80_BUILD_RECORD_PHASE"', builder)
        self.assertIn('echo "generated_source_sha256=$GENERATED_SOURCE_SHA256"', builder)
        self.assertIn('echo "native_binary_sha256=$CANDIDATE_SHA"', builder)
        self.assertIn('echo "gate_results_source=builder_executed_gates"', builder)
        self.assertIn('echo "hardcoded_gate_results=false"', builder)
        self.assertIn('install -m 0644 "$record_tmp" "$P80_BUILD_RECORD_OUTPUT"', builder)
        record_block = builder[builder.index('if [ -n "$P80_BUILD_RECORD_OUTPUT" ]; then') :]
        # Gate results are emitted from the variables assigned where each gate
        # ran, never as literal PASS / profile strings.
        for key, variable in (
            ("P80_HAOS_MEDIA_BUILD", "$P80_HAOS_MEDIA_BUILD"),
            ("PROFILE_SOURCE_GATE", "$PROFILE_SOURCE_GATE"),
            ("PROFILE_BINARY_GATE", "$PROFILE_BINARY_GATE"),
            ("P80_BINARY_MARKER_GATE", "$P80_BINARY_MARKER_GATE"),
            ("P80_BUILD_EXPECTED_SOURCE_SHA_GATE", "$EXPECTED_SOURCE_SHA_GATE"),
            ("MUSL_INTERPRETER_GATE", "$MUSL_INTERPRETER_GATE"),
            ("NO_GLIBC_DEPENDENCY", "$NO_GLIBC_DEPENDENCY"),
            ("NO_NEW_RUNTIME_DEPENDENCY", "$NO_NEW_RUNTIME_DEPENDENCY"),
            ("LIB_IDENTICAL", "$LIB_IDENTICAL"),
        ):
            self.assertIn(f'echo "{key}={variable}"', record_block)
            self.assertNotIn(f'echo "{key}=PASS"', record_block)
        self.assertNotIn('echo "PROFILE_SOURCE_GATE=$P80_BUILD_PROFILE"', record_block)
        self.assertNotIn('echo "PROFILE_BINARY_GATE=$P80_BUILD_PROFILE"', record_block)
        # Each gate variable is initialised as not-reached and only set to
        # the profile/PASS on the success branch of the gate that ran.
        for initial in (
            "PROFILE_SOURCE_GATE=NOT_REACHED",
            "PROFILE_BINARY_GATE=NOT_REACHED",
            "P80_BINARY_MARKER_GATE=NOT_REACHED",
            "EXPECTED_SOURCE_SHA_GATE=NOT_REQUESTED",
        ):
            self.assertIn(f"\n{initial}\n", builder)
        self.assertRegex(
            builder,
            r'--generated-source "\$GENERATED"; then\n\s+PROFILE_SOURCE_GATE=\$P80_BUILD_PROFILE\n',
        )
        self.assertRegex(
            builder,
            r'--strings-file "\$BUILD/candidate.strings"; then\n'
            r'\s+PROFILE_BINARY_GATE=\$P80_BUILD_PROFILE\n\s+P80_BINARY_MARKER_GATE=PASS\n',
        )

    def test_p119_diagnostic_markers_are_present_in_the_packaged_binary(self) -> None:
        # The finalisation step rebuilt the packaged ELF from the P119 source,
        # so the new diagnostic markers are now part of the shipped bytes.
        for marker in (
            b"G0_NATIVE_PROCESS_START_MONOTONIC_MS=",
            b"G1_NICE_AGENT_READY_MONOTONIC_MS=",
            b"G2_GATHER_CALL_MONOTONIC_MS=",
            b"G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS=",
            b"G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS=",
            b"G5_GATHER_DONE_MONOTONIC_MS=",
            b"G6_OFFER_WRITTEN_MONOTONIC_MS=",
            b"RSP_VISIBLE_MONOTONIC_MS=",
            b"RSP_LOADED_MONOTONIC_MS=",
        ):
            self.assertIn(marker, self.binary_blob)

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

    def test_current_head_source_identity_matches_packaged_native_provenance(self) -> None:
        sys.path.insert(0, str(MEDIA_DIR))
        from entrance_p122_on_demand_media_door_transform import transform
        import entrance_p125_ringid_probe_media_transform as p125

        candidate = transform(
            SOURCE.read_text(encoding="utf-8")
        ).encode("utf-8")
        head_sha = hashlib.sha256(candidate).hexdigest()
        meta = _metadata(BUILD_META)
        frozen_p124_meta = _metadata(FROZEN_P124_BUILD_META)
        frozen_p123_meta = _metadata(FROZEN_P123_BUILD_META)
        frozen_p117_meta = _metadata(FROZEN_P117_BUILD_META)
        native_rebuild_required = head_sha != PACKAGED_NATIVE_SOURCE_SHA256
        current_packaged_matches_head = head_sha == PACKAGED_NATIVE_SOURCE_SHA256
        frozen_p122_active_meta = _metadata(FROZEN_P122_ACTIVE_BUILD_META)
        frozen_p122_on_demand_meta = _metadata(FROZEN_P122_ON_DEMAND_BUILD_META)
        self.assertEqual(head_sha, HEAD_P116_SOURCE_SHA256)
        self.assertEqual(meta["GENERATED_SOURCE_SHA256"], PACKAGED_NATIVE_SOURCE_SHA256)
        self.assertNotEqual(meta["GENERATED_SOURCE_SHA256"], HEAD_P116_SOURCE_SHA256)
        self.assertEqual(
            hashlib.sha256(p125.transform(SOURCE.read_text(encoding="utf-8")).encode("utf-8")).hexdigest(),
            PACKAGED_NATIVE_SOURCE_SHA256,
        )
        # The observability overlay supersedes P124's active-media source
        # identity while leaving the non-overlay HEAD P116/P122 identity distinct.
        self.assertEqual(
            meta["superseded_generated_source_sha256"],
            SUPERSEDED_P124_SOURCE_SHA256,
        )
        self.assertEqual(
            frozen_p122_on_demand_meta["NATIVE_BINARY_SHA256"],
            SUPERSEDED_P122_ON_DEMAND_BINARY_SHA256,
        )
        self.assertEqual(frozen_p124_meta["NATIVE_BINARY_SHA256"], SUPERSEDED_P124_BINARY_SHA256)
        self.assertEqual(
            frozen_p124_meta["GENERATED_SOURCE_SHA256"], SUPERSEDED_P124_SOURCE_SHA256
        )
        self.assertEqual(meta["superseded_native_binary_sha256"], SUPERSEDED_P124_BINARY_SHA256)
        self.assertEqual(meta.get("binary_rebuild_pending_orchestrator", "false"), "false")
        self.assertNotEqual(head_sha, PACKAGED_NATIVE_SOURCE_SHA256)
        # The frozen P117 record must keep documenting exactly the source it
        # actually built (what this round supersedes), never the current pin.
        self.assertEqual(frozen_p117_meta["GENERATED_SOURCE_SHA256"], SUPERSEDED_P117_SOURCE_SHA256)
        self.assertNotEqual(head_sha, SUPERSEDED_R65_SOURCE_SHA256)
        self.assertNotEqual(head_sha, PRE_R65_PACKAGED_SOURCE_SHA256)
        self.assertNotEqual(head_sha, PRE_R30E_PACKAGED_SOURCE_SHA256)
        # The two diagnostic flags are derived quantities: assert they agree with the
        # facts computed above instead of snapshotting either state.
        self.assertEqual(native_rebuild_required, head_sha != PACKAGED_NATIVE_SOURCE_SHA256)
        self.assertEqual(
            current_packaged_matches_head, head_sha == PACKAGED_NATIVE_SOURCE_SHA256
        )
        self.assertTrue(native_rebuild_required or current_packaged_matches_head)

    def test_packaged_and_head_digest_pins_fail_on_byte_flip(self) -> None:
        actual_binary_sha = _sha256_bytes(self.binary_blob)
        self.assertEqual(actual_binary_sha, EXPECTED_MUSL_SHA256)
        corrupted_binary = bytearray(self.binary_blob)
        corrupted_binary[0] ^= 0x01
        corrupted_binary_sha = _sha256_bytes(bytes(corrupted_binary))
        self.assertNotEqual(corrupted_binary_sha, EXPECTED_MUSL_SHA256)
        with self.assertRaises(AssertionError):
            self.assertEqual(corrupted_binary_sha, EXPECTED_MUSL_SHA256)
        verified_promoted_p125_artifact_sha = _metadata(BUILD_META)["NATIVE_BINARY_SHA256"]
        tampered_promoted_artifact_sha = "0" * 64
        self.assertEqual(actual_binary_sha, verified_promoted_p125_artifact_sha)
        self.assertNotEqual(actual_binary_sha, tampered_promoted_artifact_sha)
        with self.assertRaises(AssertionError):
            self.assertEqual(actual_binary_sha, tampered_promoted_artifact_sha)

        sys.path.insert(0, str(MEDIA_DIR))
        from entrance_p122_on_demand_media_door_transform import transform

        candidate = transform(
            SOURCE.read_text(encoding="utf-8")
        )
        self.assertEqual(hashlib.sha256(candidate.encode("utf-8")).hexdigest(), HEAD_P116_SOURCE_SHA256)
        corrupted_candidate = candidate.replace("P116_RTP_TELEMETRY_CADENCE", "P116_RTP_TELEMETRY_CADENCE_CORRUPT", 1)
        corrupted_head_sha = hashlib.sha256(corrupted_candidate.encode("utf-8")).hexdigest()
        self.assertNotEqual(corrupted_head_sha, HEAD_P116_SOURCE_SHA256)
        with self.assertRaises(AssertionError):
            self.assertEqual(corrupted_head_sha, HEAD_P116_SOURCE_SHA256)

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
        self.assertEqual(source.count("async def async_open_door("), 1)
        self.assertIn("os.kill(process.pid, signal.SIGUSR1)", source)
        self.assertIn('"automatic_retry_allowed": False', source)
        self.assertIn('"physical_effect_asserted": False', source)
        self.assertIn('"path": "ON_DEMAND_MEDIA_SINGLE"', source)
        for forbidden in (
            "for attempt",
            "force_refresh=True",
            "create_door_message",
            "homeassistant.restart",
            "systemctl",
            'panel == "gate"',
            'panel != "entrance"',
            "LEN=24",
            "async_pause_for_media",
            "async_resume_after_media",
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
