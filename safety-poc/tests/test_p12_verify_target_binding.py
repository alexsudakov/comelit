import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p12_verify_target_binding.py"
spec = importlib.util.spec_from_file_location("p12_verify_target_binding", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


SYNTHETIC_EXPECTED = {
    "model": digest("fixture-model"),
    "version": digest("fixture-version"),
    "apt-address": digest("fixture-address"),
    "apt-subaddress": digest("9"),
}


class P12TargetBindingTests(unittest.TestCase):
    def test_nested_expected_identity_verifies(self):
        payload = {
            "server": {"model": "fixture-model", "version": "fixture-version"},
            "vip": {
                "user-parameters": {
                    "apt-address": "fixture-address",
                    "apt-subaddress": 9,
                }
            },
        }
        with mock.patch.object(module, "EXPECTED_VALUE_SHA256", SYNTHETIC_EXPECTED):
            result = module.verify_payload(json.dumps(payload).encode("utf-8"))
        self.assertTrue(result.verified)
        self.assertTrue(all(result.matches.values()))

    def test_expected_value_may_coexist_with_other_same_named_fields(self):
        payload = {
            "components": [{"version": "other"}, {"version": "fixture-version"}],
            "server": {"model": "fixture-model"},
            "identity": {"apt-address": "fixture-address", "apt-subaddress": "9"},
        }
        with mock.patch.object(module, "EXPECTED_VALUE_SHA256", SYNTHETIC_EXPECTED):
            result = module.verify_payload(json.dumps(payload).encode("utf-8"))
        self.assertTrue(result.verified)
        self.assertEqual(result.observed_scalar_counts["version"], 2)

    def test_one_mismatch_fails_closed(self):
        payload = {
            "model": "fixture-model",
            "version": "wrong",
            "apt-address": "fixture-address",
            "apt-subaddress": 9,
        }
        with mock.patch.object(module, "EXPECTED_VALUE_SHA256", SYNTHETIC_EXPECTED):
            result = module.verify_payload(json.dumps(payload).encode("utf-8"))
        self.assertFalse(result.verified)
        self.assertFalse(result.matches["version"])

    def test_public_report_never_emits_identity_values(self):
        payload = {
            "model": "fixture-model",
            "version": "fixture-version",
            "apt-address": "fixture-address",
            "apt-subaddress": 9,
        }
        with mock.patch.object(module, "EXPECTED_VALUE_SHA256", SYNTHETIC_EXPECTED):
            result = module.verify_payload(json.dumps(payload).encode("utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "target.txt"
            module.write_public_safe_report(report, result)
            text = report.read_text(encoding="utf-8")
            for value in ("fixture-model", "fixture-version", "fixture-address"):
                self.assertNotIn(value, text)
            self.assertIn("TARGET_IDENTITY_VALUES_EMITTED=false", text)
            self.assertIn("TARGET_BINDING_VERIFIED=PASS", text)
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)

    def test_repository_expected_values_are_hashes_only(self):
        self.assertEqual(
            set(module.EXPECTED_VALUE_SHA256),
            {"model", "version", "apt-address", "apt-subaddress"},
        )
        for value in module.EXPECTED_VALUE_SHA256.values():
            self.assertEqual(len(value), 64)
            int(value, 16)


if __name__ == "__main__":
    unittest.main()
