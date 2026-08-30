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
        self.assertTrue(all(result.required_unique.values()))
        self.assertTrue(all(result.optional_compatible.values()))

    def test_live_ucfg_shape_without_model_or_version_verifies(self):
        payload = {
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
        self.assertEqual(result.observed_scalar_counts["model"], 0)
        self.assertEqual(result.observed_scalar_counts["version"], 0)
        self.assertFalse(result.matches["model"])
        self.assertFalse(result.matches["version"])
        self.assertTrue(result.optional_compatible["model"])
        self.assertTrue(result.optional_compatible["version"])

    def test_optional_context_mismatch_fails_closed_when_present(self):
        payload = {
            "server": {"model": "wrong-model"},
            "identity": {"apt-address": "fixture-address", "apt-subaddress": 9},
        }
        with mock.patch.object(module, "EXPECTED_VALUE_SHA256", SYNTHETIC_EXPECTED):
            result = module.verify_payload(json.dumps(payload).encode("utf-8"))
        self.assertFalse(result.verified)
        self.assertFalse(result.optional_compatible["model"])

    def test_required_identity_must_be_unique(self):
        payload = {
            "first": {"apt-address": "fixture-address", "apt-subaddress": 9},
            "second": {"apt-address": "fixture-address"},
        }
        with mock.patch.object(module, "EXPECTED_VALUE_SHA256", SYNTHETIC_EXPECTED):
            result = module.verify_payload(json.dumps(payload).encode("utf-8"))
        self.assertFalse(result.verified)
        self.assertFalse(result.required_unique["apt-address"])
        self.assertTrue(result.required_unique["apt-subaddress"])

    def test_expected_value_may_coexist_with_other_optional_same_named_fields(self):
        payload = {
            "components": [{"version": "other"}, {"version": "fixture-version"}],
            "server": {"model": "fixture-model"},
            "identity": {"apt-address": "fixture-address", "apt-subaddress": "9"},
        }
        with mock.patch.object(module, "EXPECTED_VALUE_SHA256", SYNTHETIC_EXPECTED):
            result = module.verify_payload(json.dumps(payload).encode("utf-8"))
        self.assertTrue(result.verified)
        self.assertEqual(result.observed_scalar_counts["version"], 2)
        self.assertTrue(result.optional_compatible["version"])

    def test_required_mismatch_fails_closed(self):
        payload = {
            "model": "fixture-model",
            "version": "fixture-version",
            "apt-address": "wrong-address",
            "apt-subaddress": 9,
        }
        with mock.patch.object(module, "EXPECTED_VALUE_SHA256", SYNTHETIC_EXPECTED):
            result = module.verify_payload(json.dumps(payload).encode("utf-8"))
        self.assertFalse(result.verified)
        self.assertFalse(result.matches["apt-address"])

    def test_public_report_never_emits_identity_values(self):
        payload = {
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
            self.assertIn("P12_TARGET_BINDING_SCHEMA=2", text)
            self.assertIn("P12_TARGET_REQUIRED_IDENTITY=APT_ADDRESS_PLUS_APT_SUBADDRESS", text)
            self.assertIn("P12_TARGET_APT_ADDRESS_UNIQUE=true", text)
            self.assertIn("P12_TARGET_APT_SUBADDRESS_UNIQUE=true", text)
            self.assertIn("P12_TARGET_MODEL_CONTEXT_COMPATIBLE=true", text)
            self.assertIn("P12_TARGET_VERSION_CONTEXT_COMPATIBLE=true", text)
            self.assertIn("TARGET_IDENTITY_VALUES_EMITTED=false", text)
            self.assertIn("TARGET_BINDING_VERIFIED=PASS", text)
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)

    def test_repository_expected_values_are_hashes_only(self):
        self.assertEqual(
            set(module.EXPECTED_VALUE_SHA256),
            {"model", "version", "apt-address", "apt-subaddress"},
        )
        self.assertEqual(module.REQUIRED_UNIQUE_KEYS, ("apt-address", "apt-subaddress"))
        self.assertEqual(module.OPTIONAL_CONTEXT_KEYS, ("model", "version"))
        for value in module.EXPECTED_VALUE_SHA256.values():
            self.assertEqual(len(value), 64)
            int(value, 16)


if __name__ == "__main__":
    unittest.main()
