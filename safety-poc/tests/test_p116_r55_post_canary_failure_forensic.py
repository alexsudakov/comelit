#!/usr/bin/env python3
"""P116/R55 premature-publication corrective offline tests."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
FROZEN = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r45_call_adoption_core as r45  # noqa: E402
import entrance_p116_r53_call_adoption_profile_core as r53  # noqa: E402
import entrance_p116_r54_call_adoption_listener_transform as r54  # noqa: E402
import entrance_p116_r55_call_adoption_observability_corrective as r55  # noqa: E402


class P116R55PrematurePublicationCorrectiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = FROZEN.read_text(encoding="utf-8")
        cls.generated_a = r54.transform(source)
        cls.generated_b = r54.transform(source)
        cls.r54_region = cls.generated_a.split(r54.BEGIN, 1)[1].split(r54.END, 1)[0]
        cls.r53_region = cls.generated_a.split(
            r53.CORE_BEGIN_MARKER, 1
        )[1].split(r53.CORE_END_MARKER, 1)[0]

    def test_no_peer_scope_field_can_be_published_in_local_phase(self) -> None:
        self.assertIn("R54_DIAGNOSTICS_PHASE=%s", self.r54_region)
        self.assertIn("R54_DIAGNOSTICS_LOCAL_AFTER_TRIO", self.r54_region)
        self.assertIn("R54_PEER_CAPABILITIES_SEEN=NOT_REACHED", self.r54_region)
        self.assertIn("R54_PEER_CAPABILITY_WORD=NOT_REACHED", self.r54_region)
        self.assertIn("R54_PEER_VIDEO_REQUESTED=NOT_REACHED", self.r54_region)

        local_block = self.r54_region.split("if (peer_phase_reached)", 1)[0]
        for forbidden in (
            'diag->peer_capabilities_seen ? "true" : "false"',
            "diag->peer_capability_word",
            'diag->peer_video_requested ? "true" : "false"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, local_block)

    def test_peer_wait_terminal_marker_is_generation_end_only(self) -> None:
        self.assertIn("R54_DIAGNOSTICS_GENERATION_END", self.generated_a)
        self.assertIn("R54_PEER_WAIT_ENDED_WITHOUT_CAPABILITIES=%s", self.r54_region)
        terminal_block = self.r54_region.split(
            "phase == R54_DIAGNOSTICS_GENERATION_END", 1
        )[1]
        self.assertIn("diag->waiting_peer_capabilities", terminal_block)
        self.assertIn("!diag->peer_capabilities_seen", terminal_block)

    def test_peer_only_ack_counter_exists_and_is_used(self) -> None:
        self.assertIn("unsigned peer_data_ack_count;", r45.CORE_REGION)
        self.assertIn("state->peer_data_ack_count += 1u;", r45.CORE_REGION)
        self.assertIn("state->r45.peer_data_ack_count > 0u", self.r54_region)
        self.assertNotIn("state->r45.inbound_ack_count > 0u", self.r54_region)

    def test_generator_produces_corrected_region_text_deterministically(self) -> None:
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertIn("R54_DIAGNOSTICS_PHASE=%s", self.generated_a)
        self.assertIn("R54_PEER_CAPABILITIES_SEEN=NOT_REACHED", self.generated_a)
        self.assertIn("R54_PEER_WAIT_ENDED_WITHOUT_CAPABILITIES=%s", self.generated_a)
        self.assertIn("state->r45.peer_data_ack_count > 0u", self.generated_a)
        self.assertIn("r54_publish_diagnostics(", self.generated_a)

    def test_peer_capabilities_seen_only_true_through_peer_validation_path(self) -> None:
        assignment = "state->diag.peer_capabilities_seen = 1;"
        self.assertEqual(self.r53_region.count(assignment), 1)
        before_assignment = self.r53_region.split(assignment, 1)[0]
        self.assertIn("r36_is_capabilities_for_current_call(session, peer_view)", before_assignment)
        self.assertIn("r53_peer_capability_word(peer_view, &word)", before_assignment)
        self.assertNotIn(assignment, self.r54_region)

    def test_region_source_verifier_is_not_generated_text_patch(self) -> None:
        r55.verify_region_sources()
        text = Path(r55.__file__).read_text(encoding="utf-8")
        self.assertIn("GENERATED_TEXT_PATCH=false", text)
        self.assertNotIn("def transform(", text)
        self.assertNotIn("replace(old", text)


if __name__ == "__main__":
    unittest.main()
