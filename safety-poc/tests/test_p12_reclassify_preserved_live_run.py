import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p12_reclassify_preserved_live_run.py"
spec = importlib.util.spec_from_file_location("p12_reclassify_preserved_live_run", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


SERVICE = """\
P12_LIVE_SERVICE_PAYLOAD_START=true
P12_ONE_SHOT_PROCESS_INVOCATIONS=1
P12_ONE_SHOT_AUTO_RETRY=false
P12_ONE_SHOT_PROCESS_GROUP_ISOLATED=true
TIMEOUT_MAPPING_VERIFIED=PASS
P12_READONLY_LIVE_RUN_PERFORMED=true
P12_READONLY_LIVE_WRAPPER_INVOCATIONS=1
P12_READONLY_LIVE_WRAPPER_OUTCOME=COMPLETED
P12_READONLY_LIVE_WRAPPER_RC=0
P2_VIP_UAUT_AUTH=PASS
UAUT_RESPONSE_CODE=200
VIP_UAUT_CLOSE_RESPONSE=PASS
VIP_UAUT_CLOSE_RESPONSE_WORD=0
VIP_UCFG_OPEN_RESPONSE=PASS
VIP_UCFG_OPEN_RESPONSE_WORD=0
UCFG_RECEIVED=true
UCFG_RESPONSE_SHA256=abc123
VIP_UCFG_CLOSE_RESPONSE=PASS
VIP_UCFG_CLOSE_RESPONSE_WORD=0
P12_READONLY_TRANSACTION=PASS
P12_AUTH_SESSION_LIFETIME_SEQUENCE=PASS
READONLY_SCOPE_ENFORCED=PASS
CREDENTIAL_MATERIAL_EMITTED=false
ACTUATOR_COMMAND_ATTEMPTED=false
AUTO_RETRY_OBSERVED=false
PHYSICAL_DOOR_ACTION=false
PHYSICAL_EFFECT_ASSERTED=false
P12_LIVE_SERVICE_PAYLOAD_END=true
"""

TARGET = """\
P12_TARGET_BINDING_SCHEMA=2
UCFG_RESPONSE_SHA256=abc123
P12_TARGET_REQUIRED_IDENTITY=APT_ADDRESS_PLUS_APT_SUBADDRESS
P12_TARGET_REQUIRED_UNIQUE=true
P12_TARGET_APT_ADDRESS_MATCH=true
P12_TARGET_APT_SUBADDRESS_MATCH=true
P12_TARGET_APT_ADDRESS_UNIQUE=true
P12_TARGET_APT_SUBADDRESS_UNIQUE=true
P12_TARGET_MODEL_CONTEXT_COMPATIBLE=true
P12_TARGET_VERSION_CONTEXT_COMPATIBLE=true
TARGET_IDENTITY_VALUES_EMITTED=false
CREDENTIAL_MATERIAL_EMITTED=false
ACTUATOR_COMMAND_ATTEMPTED=false
PHYSICAL_DOOR_ACTION=false
TARGET_BINDING_VERIFIED=PASS
"""


class P12PreservedLiveReclassificationTests(unittest.TestCase):
    def test_valid_preserved_run_opens_readonly_live_gates(self):
        result = module.reclassify(SERVICE, TARGET)
        self.assertEqual(result["P12_PRESERVED_LIVE_RECLASSIFICATION"], "PASS")
        self.assertEqual(result["P12_READONLY_LIVE_GATES"], "PASS")
        self.assertEqual(result["TARGET_BINDING_VERIFIED"], "PASS")
        self.assertEqual(result["ACTUATOR_COMMAND_ATTEMPTED"], "false")

    def test_ucfg_hash_mismatch_fails_closed(self):
        with self.assertRaises(RuntimeError):
            module.reclassify(SERVICE, TARGET.replace("abc123", "different", 1))

    def test_second_invocation_marker_fails_closed(self):
        with self.assertRaises(RuntimeError):
            module.reclassify(SERVICE.replace("P12_ONE_SHOT_PROCESS_INVOCATIONS=1", "P12_ONE_SHOT_PROCESS_INVOCATIONS=2"), TARGET)

    def test_target_mismatch_fails_closed(self):
        with self.assertRaises(RuntimeError):
            module.reclassify(SERVICE, TARGET.replace("P12_TARGET_APT_ADDRESS_MATCH=true", "P12_TARGET_APT_ADDRESS_MATCH=false"))

    def test_report_is_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gates.txt"
            module.write_report(path, module.reclassify(SERVICE, TARGET))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_source_has_no_network_or_process_execution(self):
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("subprocess", "socket", "requests", "urllib", "os.system", "Popen(", "run("):
            self.assertNotIn(forbidden, text)
        self.assertIn("NETWORK_ACTION_PERFORMED=false", text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", text)


if __name__ == "__main__":
    unittest.main()
