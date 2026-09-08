#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_p77_receive_path_static_contract as p77_static


class P77ReceivePathStaticContractTests(unittest.TestCase):
    def test_static_table_is_bounded_and_valid(self) -> None:
        p77_static.validate_contract()
        self.assertGreaterEqual(len(p77_static.FINDINGS), 8)
        symbols = {finding.symbol for finding in p77_static.FINDINGS}
        self.assertIn("RtpDispatcher::threadVideoRX()", symbols)
        self.assertIn("RtpDispatcher::threadAudioRX()", symbols)
        self.assertTrue(any("setReceivedCbk" in symbol for symbol in symbols))
        self.assertTrue(any("openMediaRXChannel" in symbol for symbol in symbols))

    def test_partial_claims_stay_partial(self) -> None:
        text = p77_static.report()
        self.assertIn("RTPC_RECEIVE_PATH_STATIC_PROVENANCE=PARTIAL", text)
        self.assertIn("NOT_PROVEN=EXACT_RTPC_CALLBACK_CALL_GRAPH", text)
        self.assertIn("LISTENER_STOP_REQUIRED=NOT_PROVEN", text)
        self.assertNotIn("RTPC_RECEIVE_PATH_STATIC_PROVENANCE=PROVEN_OFFLINE", text)

    def test_static_module_has_no_network_or_launcher_surface(self) -> None:
        source = Path(p77_static.__file__).read_text()
        for token in ("socket", "requests", "urllib", "ct120_launch_", "ct120_run_"):
            self.assertNotIn(token, source)
        self.assertIn("NETWORK_IO_PERFORMED=false", source)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", source)


if __name__ == "__main__":
    unittest.main()
