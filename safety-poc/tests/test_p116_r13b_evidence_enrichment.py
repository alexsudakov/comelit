from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".p116-evidence"
HA = EVIDENCE / "ha-2026.9.1"
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
PRIVATE_HA_EVIDENCE_READY = all(
    (HA / name).is_file()
    for name in (
        "RETRIEVAL_MANIFEST.tsv",
        "hls.py",
        "fmp4utils.py",
        "worker.py",
        "core.py",
        "const.py",
        "__init__.py",
    )
)


SAFE_REDACTION_R13B = re.compile(
    r"^(?:PASS|FAIL|true|false|READY|OPEN|CLOSED|UNKNOWN_OUTCOME|"
    r"REJECTED|REJECTED_NOT_READY|FAILED_SAFE|EXPECTED_TERMINAL_SHUTDOWN|"
    r"FATAL|NONE|HOME_ASSISTANT|STATE_SCOPED_STRUCTURAL|NOT_MATCHED|ACTIVE|"
    r"PREACTIVE|DISCONNECTED|GATHERING|CONNECTING|CONNECTED|FAILED|"
    r"\d{1,20}|\d{1,3}(?:,\d{1,3}){0,127}|"
    r"\d{1,5} OPEN=(?:true|false) ACK=(?:true|false)|"
    r"FAIL LEN=\d{1,5})$"
)


class P116R13BEvidenceEnrichmentTests(unittest.TestCase):
    @unittest.skipUnless(
        PRIVATE_HA_EVIDENCE_READY,
        "private HA 2026.9.1 evidence unavailable",
    )
    def test_ha_2026_9_1_evidence_closes_hls_import_closure(self) -> None:
        manifest = (HA / "RETRIEVAL_MANIFEST.tsv").read_text(encoding="utf-8")
        for name in ("hls.py", "fmp4utils.py", "worker.py", "core.py", "const.py", "__init__.py"):
            self.assertTrue((HA / name).is_file(), name)
            self.assertIn(f"stream/{name}", manifest)
        hls_source = (HA / "hls.py").read_text(encoding="utf-8")
        self.assertIn("from .const import", hls_source)
        self.assertIn("from .core import", hls_source)
        self.assertIn("from .fmp4utils import", hls_source)

    def test_r13b_probe_is_socket_free_and_length_prefixed(self) -> None:
        source = (MEDIA / "entrance_p116_r13b_offline_hls_probe.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("uint16 big-endian length followed by one UDP payload", source)
        self.assertIn("int.from_bytes(data[pos : pos + 2], \"big\")", source)
        self.assertIn("container_options=options", source)
        self.assertIn('"frag_duration": "900000"', source)
        self.assertNotIn("socket.", source)
        self.assertNotIn("bind(", source)
        self.assertNotIn("sendto(", source)

    def test_redaction_shape_proposal_is_anchored_not_catch_all(self) -> None:
        for safe in (
            "HOME_ASSISTANT",
            "123 OPEN=true ACK=false",
            "PSEUDOTCP_APP_RX_EVENT=123 OPEN=true ACK=false".split("=", 1)[1],
            "FAIL LEN=24",
        ):
            self.assertRegex(safe, SAFE_REDACTION_R13B)
        for secretish in (
            "abc123TOKEN456secret",
            "192.168.1.50:3478",
            "123 OPEN=true ACK=false EXTRA=secret",
            "FAIL LEN=24 TOKEN=abc",
        ):
            self.assertIsNone(SAFE_REDACTION_R13B.fullmatch(secretish), secretish)


if __name__ == "__main__":
    unittest.main()
