import unittest

from comelit_safety_poc.p12_transport_model import (
    P12P2PContract,
    P12P2PEvidence,
    P12_READONLY_P2P_PLAN,
    default_p12_contract,
    validate_p12_plan,
)


class P12TransportModelTests(unittest.TestCase):
    def test_default_contract_is_readonly_and_p2p_only(self):
        contract = default_p12_contract()
        self.assertFalse(contract.direct_tcp_primary_path_allowed)
        self.assertTrue(contract.cloud_signaling_allowed)
        self.assertTrue(contract.ice_allowed)
        self.assertTrue(contract.pseudotcp_allowed)
        self.assertFalse(contract.actuator_command_allowed)
        self.assertFalse(contract.media_activation_allowed)
        self.assertFalse(contract.automatic_retry_allowed)

    def test_actuation_or_media_invalidates_contract(self):
        for kwargs in (
            {"actuator_command_allowed": True},
            {"media_activation_allowed": True},
            {"automatic_retry_allowed": True},
            {"credential_export_allowed": True},
            {"physical_effect_assertion_allowed": True},
            {"direct_tcp_primary_path_allowed": True},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    P12P2PContract(**kwargs).validate()

    def test_complete_evidence_requires_uaut_auth_ucfg_and_clean_teardown(self):
        evidence = P12P2PEvidence(
            cloud_signaling=True,
            ice_connected=True,
            pseudotcp_open=True,
            vip_echo_ack=True,
            uaut_open=True,
            uaut_auth_200=True,
            ucfg_observed=True,
            clean_teardown=True,
        )
        self.assertTrue(evidence.readonly_transport_proof_complete)

        self.assertFalse(
            P12P2PEvidence(
                cloud_signaling=True,
                ice_connected=True,
                pseudotcp_open=True,
                vip_echo_ack=True,
                uaut_open=True,
                uaut_auth_200=False,
                ucfg_observed=False,
                clean_teardown=True,
            ).readonly_transport_proof_complete
        )

    def test_any_actuation_marker_invalidates_evidence(self):
        evidence = P12P2PEvidence(
            cloud_signaling=True,
            ice_connected=True,
            pseudotcp_open=True,
            vip_echo_ack=True,
            uaut_open=True,
            uaut_auth_200=True,
            ucfg_observed=True,
            clean_teardown=True,
            actuator_command_attempted=True,
        )
        self.assertFalse(evidence.readonly_transport_proof_complete)

    def test_plan_is_fixed(self):
        validate_p12_plan(P12_READONLY_P2P_PLAN)
        with self.assertRaises(ValueError):
            validate_p12_plan(P12_READONLY_P2P_PLAN[:-1])


if __name__ == "__main__":
    unittest.main()
