import unittest

from comelit_safety_poc.ha_contract import HaDoorRequest, HaDoorResult, HaResultState, HaServiceContract


class HaContractTests(unittest.TestCase):
    def test_canonical_service_is_one_shot_and_unknown_visible(self):
        contract = HaServiceContract()
        self.assertEqual((contract.domain, contract.service), ("comelit", "open_door"))
        self.assertTrue(contract.requires_operation_id)
        self.assertFalse(contract.automatic_retry)
        self.assertTrue(contract.exposes_unknown_outcome)
        self.assertFalse(contract.physical_state_claims)

    def test_request_requires_operation_id_and_target(self):
        with self.assertRaises(ValueError):
            HaDoorRequest("", "door")
        with self.assertRaises(ValueError):
            HaDoorRequest("op", "")

    def test_result_forbids_retry_and_physical_claim(self):
        result = HaDoorResult(operation_id="op", target="door", state=HaResultState.UNKNOWN_OUTCOME, retry_allowed=False)
        self.assertFalse(result.retry_allowed)
        with self.assertRaises(ValueError):
            HaDoorResult("op", "door", HaResultState.ACKED, True)
        with self.assertRaises(ValueError):
            HaDoorResult("op", "door", HaResultState.ACKED, False, physical_effect_asserted=True)


if __name__ == "__main__":
    unittest.main()
