import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "safety-poc/research/door/v1_5_3/comelit-v4-persistent-ctpp-door.c"
)
TRANSFORM_PATH = (
    ROOT
    / "safety-poc/research/media/v1/pseudotcp_prestart_replay_transform.py"
)

spec = importlib.util.spec_from_file_location(
    "pseudotcp_prestart_replay_transform",
    TRANSFORM_PATH,
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class P18PseudoTcpPrestartReplayContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original = SOURCE.read_text(encoding="utf-8")
        cls.candidate = module.transform(cls.original)

    def test_original_exposes_the_race_boundary(self):
        self.assertIn('"PSEUDOTCP_RX_BEFORE_START=%u\\n"', self.original)
        self.assertIn("if (!pseudo_tcp) {", self.original)
        self.assertIn("pseudo_tcp_socket_connect(\n            pseudo_tcp)", self.original)

    def test_candidate_preserves_packet_boundaries_in_bounded_queue(self):
        text = self.candidate
        self.assertIn("#define PSEUDOTCP_PRESTART_MAX_PACKETS 8", text)
        self.assertIn("#define PSEUDOTCP_PRESTART_MAX_LEN     2048", text)
        self.assertIn("pseudotcp_prestart_lengths", text)
        self.assertIn('"PSEUDOTCP_RX_BUFFERED=%u LEN=%u\\n"', text)
        self.assertIn('"PSEUDOTCP_PRESTART_BUFFER=FAIL LEN=%u COUNT=%u\\n"', text)
        self.assertNotIn('"PSEUDOTCP_RX_BEFORE_START=%u\\n"', text)

    def test_candidate_replays_before_local_connect_decision(self):
        text = self.candidate
        replay = text.index("if (!replay_pseudotcp_prestart_packets())")
        get_state = text.index('"state",', replay)
        connect = text.index("pseudo_tcp_socket_connect(\n                pseudo_tcp)", get_state)
        self.assertLess(replay, get_state)
        self.assertLess(get_state, connect)

    def test_candidate_allows_peer_initiated_handshake(self):
        text = self.candidate
        self.assertIn("pseudotcp_state == PSEUDO_TCP_SYN_RECEIVED", text)
        self.assertIn("pseudotcp_state == PSEUDO_TCP_ESTABLISHED", text)
        self.assertIn(
            '"PSEUDOTCP_CONNECT_START=SKIPPED_PEER_INITIATED\\n"',
            text,
        )

    def test_candidate_still_initiates_when_socket_remains_listening(self):
        text = self.candidate
        self.assertIn("pseudotcp_state == PSEUDO_TCP_LISTEN", text)
        self.assertIn('printf("PSEUDOTCP_CONNECT_START=PASS\\n");', text)

    def test_candidate_does_not_change_door_contract(self):
        text = self.candidate
        self.assertIn("static const guint v4_door_write_count = 5;", text)
        self.assertIn('v4_door_emit_result("UNKNOWN_OUTCOME")', text)
        self.assertIn("v4_ctpp_channel_id", text)
        for forbidden in (
            "V4_DOOR_CTPP_OPEN_SENT=true",
            "V4_DOOR_CTPP_CLOSE_SENT=true",
            "V4_DOOR_WRITE_%u_ACKED=true",
        ):
            self.assertNotIn(forbidden, text)

    def test_transform_is_research_only_and_non_actuating(self):
        transform_text = TRANSFORM_PATH.read_text(encoding="utf-8")
        self.assertIn("NETWORK_IO_PERFORMED=false", transform_text)
        self.assertIn("DOOR_ACTION_SENT=false", transform_text)
        self.assertIn("MEDIA_ACTION_SENT=false", transform_text)


if __name__ == "__main__":
    unittest.main()
