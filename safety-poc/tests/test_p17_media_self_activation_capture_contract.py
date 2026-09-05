import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    ROOT
    / "safety-poc/research/media/v1/entrance_self_activation_capture.json"
)


class P17MediaSelfActivationCaptureContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = FIXTURE.read_text(encoding="utf-8")
        cls.data = json.loads(cls.raw)

    def test_fixture_is_non_actuating_and_offline(self):
        scope = self.data["scope"]
        self.assertFalse(scope["network_io_performed_by_fixture"])
        self.assertFalse(scope["door_action_sent"])
        self.assertFalse(scope["media_action_sent"])

    def test_capture_identity_is_frozen(self):
        source = self.data["source"]
        self.assertEqual(
            source["pcap_sha256"],
            "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a",
        )
        self.assertEqual(source["packet_count"], 3546)
        self.assertEqual(source["linktype"], 101)

    def test_official_self_activation_reuses_one_persistent_ctpp(self):
        channel = self.data["channel_contract"]
        self.assertEqual(channel["ctpp_open_count"], 1)
        self.assertEqual(channel["cspb_open_count"], 1)
        self.assertTrue(channel["persistent_ctpp_request_id_reused"])
        self.assertFalse(channel["second_ctpp_open_before_self_activation"])

    def test_self_activation_signal_order_is_frozen(self):
        sequence = self.data["sequence"]
        self.assertEqual(
            [item["step"] for item in sequence],
            [
                "ctpp_registration_init",
                "self_activation_request",
                "self_activation_ack",
                "client_video_event",
                "client_video_event_ack",
                "device_video_event",
            ],
        )
        self.assertEqual(
            [(item["prefix"], item["action"]) for item in sequence],
            [
                ("0x18C0", "0x0011"),
                ("0x18C0", "0x0028"),
                ("0x1800", "0x0000"),
                ("0x1840", "0x0008"),
                ("0x1800", "0x0000"),
                ("0x1840", "0x0008"),
            ],
        )
        self.assertEqual(
            [item["direction"] for item in sequence],
            [
                "client_to_device",
                "client_to_device",
                "device_to_client",
                "client_to_device",
                "device_to_client",
                "device_to_client",
            ],
        )

    def test_body_lengths_and_hashes_are_capture_bound(self):
        expected = {
            "ctpp_registration_init": (
                52,
                "362a500bb1f322eb192afef045b25b22dd49e299016fe1ccece0cb62e81a26aa",
            ),
            "self_activation_request": (
                72,
                "67f31e080257cb67afe499feedbc156a3112677a1fadbf1f4909d96f17118378",
            ),
            "self_activation_ack": (
                32,
                "7c142177dc4800ea81882b0bc5fdda98137fa05c53b6710bc23558f95d764a06",
            ),
            "client_video_event": (
                40,
                "4c4af4d5a6786d284a13e7c172dfdc10ce147c100863c6aea9f1e38d3698294f",
            ),
            "client_video_event_ack": (
                32,
                "5713227f1d6f95d5b1f13aabc9ff79cea45ec8a5fb9e7f6bf2edca3b3ae631ee",
            ),
            "device_video_event": (
                40,
                "fbb8884012c7b6f0202a2a1418ffaf0ac06b5cbfe66a823b4d7780e559c4b02b",
            ),
        }
        for item in self.data["sequence"]:
            self.assertEqual(
                (item["body_length"], item["body_sha256"]),
                expected[item["step"]],
            )

    def test_capture_fixture_does_not_publish_protocol_addresses(self):
        for sensitive_identity in (
            "000401177",
            "00040117",
            "00000643",
            "192.248.183.213",
            "10.215.173.1",
        ):
            self.assertNotIn(sensitive_identity, self.raw)

    def test_previous_live_failure_boundary_is_preserved(self):
        boundary = self.data["next_live_boundary"]
        self.assertEqual(boundary["required_before_signaling"], "pseudotcp_open")
        self.assertEqual(
            boundary["previous_live_attempt_reached"],
            "ice_ready_without_pseudotcp_open",
        )
        self.assertTrue(
            boundary["must_not_send_self_activation_before_pseudotcp_open"]
        )
        self.assertFalse(boundary["production_camera_entities_allowed"])

    def test_media_transport_claim_remains_conservative(self):
        transport = self.data["observed_transport"]
        self.assertEqual(transport["dominant_peer_to_client_udp_packets"], 2491)
        self.assertEqual(transport["dominant_client_to_peer_udp_packets"], 883)
        self.assertTrue(transport["large_udp_payload_observed"])
        self.assertEqual(transport["largest_listed_udp_length"], 1438)
        self.assertEqual(
            transport["classification"], "media_like_transport_evidence"
        )
        self.assertIn("does not prove", transport["limitation"])


if __name__ == "__main__":
    unittest.main()
