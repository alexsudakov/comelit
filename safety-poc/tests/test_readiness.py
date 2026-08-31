import unittest

from comelit_safety_poc.readiness import (
    LIVE_GATES,
    READONLY_GATES,
    REPOSITORY_GATES,
    evaluate_readiness,
    parse_markers,
)


class ReadinessTests(unittest.TestCase):
    def test_repository_can_be_ready_while_readonly_and_live_stay_closed(self):
        evidence = {key: expected for key, expected in REPOSITORY_GATES}
        report = evaluate_readiness(evidence)
        self.assertTrue(report.repository_ready)
        self.assertFalse(report.readonly_transport_ready)
        self.assertFalse(report.live_test_ready)
        self.assertTrue(report.missing_or_failed)

    def test_readonly_transport_requires_every_readonly_gate(self):
        evidence = {key: expected for key, expected in REPOSITORY_GATES + READONLY_GATES}
        report = evaluate_readiness(evidence)
        self.assertTrue(report.repository_ready)
        self.assertTrue(report.readonly_transport_ready)
        self.assertFalse(report.live_test_ready)

        evidence["ACTUATOR_COMMAND_ATTEMPTED"] = "true"
        report = evaluate_readiness(evidence)
        self.assertTrue(report.repository_ready)
        self.assertFalse(report.readonly_transport_ready)
        self.assertFalse(report.live_test_ready)

    def test_live_test_requires_readonly_plus_every_explicit_live_gate(self):
        evidence = {key: expected for key, expected in REPOSITORY_GATES + READONLY_GATES + LIVE_GATES}
        report = evaluate_readiness(evidence)
        self.assertTrue(report.repository_ready)
        self.assertTrue(report.readonly_transport_ready)
        self.assertTrue(report.live_test_ready)

        evidence["EXPLICIT_LIVE_TEST_APPROVAL"] = "false"
        report = evaluate_readiness(evidence)
        self.assertTrue(report.repository_ready)
        self.assertTrue(report.readonly_transport_ready)
        self.assertFalse(report.live_test_ready)

    def test_marker_parser_is_simple_and_non_executing(self):
        markers = parse_markers("A=1\nNOT A MARKER\nB=false\n")
        self.assertEqual(markers, {"A": "1", "B": "false"})


if __name__ == "__main__":
    unittest.main()
