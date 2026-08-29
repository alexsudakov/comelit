import unittest

from comelit_safety_poc.control_plane_model import ControlOutcome, ControlState, SyntheticCtppControlPlane


class ControlPlaneModelTests(unittest.TestCase):
    def test_open_and_close_once(self):
        control = SyntheticCtppControlPlane()
        evidence = control.open_once()
        self.assertEqual(evidence.outcome, ControlOutcome.OPENED)
        self.assertEqual(evidence.state, ControlState.OPENED)
        self.assertEqual(evidence.binding.channel_name, "CTPP")
        self.assertEqual(evidence.binding.channel_id, 7449)
        self.assertTrue(evidence.protocol_acknowledged)
        self.assertFalse(evidence.physical_effect_asserted)
        self.assertEqual(control.close_once(), ControlState.CLOSED)
        self.assertEqual(control.open_calls, 1)
        self.assertEqual(control.close_calls, 1)

    def test_no_second_open_or_close(self):
        control = SyntheticCtppControlPlane()
        control.open_once()
        with self.assertRaises(AssertionError):
            control.open_once()
        control = SyntheticCtppControlPlane()
        control.open_once()
        control.close_once()
        with self.assertRaises(AssertionError):
            control.close_once()

    def test_ambiguous_open_never_creates_binding(self):
        control = SyntheticCtppControlPlane(open_outcome=ControlOutcome.AMBIGUOUS)
        evidence = control.open_once()
        self.assertEqual(evidence.state, ControlState.UNKNOWN)
        self.assertIsNone(evidence.binding)
        self.assertFalse(evidence.protocol_acknowledged)


if __name__ == "__main__":
    unittest.main()
