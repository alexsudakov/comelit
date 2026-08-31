import unittest

from comelit_safety_poc.readonly_session import (
    READONLY_SESSION_PLAN,
    ReadonlyCapabilityContract,
    ReadonlySessionEvidence,
    ReadonlyStep,
    default_readonly_contract,
    validate_readonly_plan,
)


class ReadonlySessionTests(unittest.TestCase):
    def test_default_contract_is_fail_closed_for_actuation(self):
        contract = default_readonly_contract()
        self.assertTrue(contract.session_control_io_allowed)
        self.assertTrue(contract.configuration_queries_allowed)
        self.assertTrue(contract.target_discovery_allowed)
        self.assertFalse(contract.actuator_command_allowed)
        self.assertFalse(contract.credential_export_allowed)
        self.assertFalse(contract.automatic_retry_allowed)
        self.assertFalse(contract.physical_effect_assertion_allowed)

    def test_actuator_or_retry_capability_is_rejected(self):
        with self.assertRaises(ValueError):
            ReadonlyCapabilityContract(actuator_command_allowed=True).validate()
        with self.assertRaises(ValueError):
            ReadonlyCapabilityContract(automatic_retry_allowed=True).validate()
        with self.assertRaises(ValueError):
            ReadonlyCapabilityContract(credential_export_allowed=True).validate()
        with self.assertRaises(ValueError):
            ReadonlyCapabilityContract(physical_effect_assertion_allowed=True).validate()

    def test_plan_is_fixed_to_five_readonly_steps(self):
        validate_readonly_plan(READONLY_SESSION_PLAN)
        self.assertEqual(
            READONLY_SESSION_PLAN,
            (
                ReadonlyStep.CONNECT,
                ReadonlyStep.AUTHENTICATE,
                ReadonlyStep.LOAD_CONFIGURATION,
                ReadonlyStep.DISCOVER_TARGETS,
                ReadonlyStep.CLOSE,
            ),
        )
        with self.assertRaises(ValueError):
            validate_readonly_plan(READONLY_SESSION_PLAN[:-1])

    def test_session_proof_requires_clean_readonly_completion(self):
        good = ReadonlySessionEvidence(True, True, True, True, True)
        self.assertTrue(good.session_proof_complete)

        self.assertFalse(
            ReadonlySessionEvidence(True, True, True, True, True, actuator_command_attempted=True).session_proof_complete
        )
        self.assertFalse(
            ReadonlySessionEvidence(True, True, True, True, True, credential_material_emitted=True).session_proof_complete
        )
        self.assertFalse(
            ReadonlySessionEvidence(True, True, True, True, True, automatic_retry_observed=True).session_proof_complete
        )
        self.assertFalse(
            ReadonlySessionEvidence(True, True, True, True, True, physical_effect_asserted=True).session_proof_complete
        )


if __name__ == "__main__":
    unittest.main()
