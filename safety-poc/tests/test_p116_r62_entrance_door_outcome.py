from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "custom_components" / "comelit" / "door_outcome.py"


def load_module():
    spec = importlib.util.spec_from_file_location("p116_r62_door_outcome", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load door_outcome.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


door_outcome = load_module()


class P116R62EntranceDoorOutcomeTests(unittest.TestCase):
    def test_complete_unknown_outcome_is_transmitted_but_unconfirmed(self) -> None:
        self.assertTrue(
            door_outcome.door_one_shot_sequence_sent(
                state="UNKNOWN_OUTCOME",
                write_count=5,
                existing_ctpp_reused=True,
            )
        )

    def test_complete_acked_outcome_is_transmitted(self) -> None:
        self.assertTrue(
            door_outcome.door_one_shot_sequence_sent(
                state="ACKED",
                write_count=5,
                existing_ctpp_reused=True,
            )
        )

    def test_partial_write_is_not_complete_transmission(self) -> None:
        self.assertFalse(
            door_outcome.door_one_shot_sequence_sent(
                state="UNKNOWN_OUTCOME",
                write_count=4,
                existing_ctpp_reused=True,
            )
        )

    def test_rejected_result_is_not_complete_transmission(self) -> None:
        self.assertFalse(
            door_outcome.door_one_shot_sequence_sent(
                state="REJECTED_NOT_READY",
                write_count=5,
                existing_ctpp_reused=True,
            )
        )

    def test_missing_persistent_ctpp_proof_is_fail_closed(self) -> None:
        self.assertFalse(
            door_outcome.door_one_shot_sequence_sent(
                state="UNKNOWN_OUTCOME",
                write_count=5,
                existing_ctpp_reused=False,
            )
        )

    def test_boolean_write_count_is_not_accepted_as_integer_five(self) -> None:
        self.assertFalse(
            door_outcome.door_one_shot_sequence_sent(
                state="UNKNOWN_OUTCOME",
                write_count=True,
                existing_ctpp_reused=True,
            )
        )

    def test_malformed_state_fails_closed(self) -> None:
        self.assertFalse(
            door_outcome.door_one_shot_sequence_sent(
                state={"unexpected": "mapping"},
                write_count=5,
                existing_ctpp_reused=True,
            )
        )

    def test_classifier_never_claims_physical_effect_or_protocol_ack(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("physical_effect_asserted = True", source)
        self.assertNotIn("protocol_acked = True", source)
        self.assertIn("weaker than protocol acknowledgement", source)


if __name__ == "__main__":
    unittest.main()
