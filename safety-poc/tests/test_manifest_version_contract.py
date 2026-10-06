import unittest

from manifest_version_contract import is_valid_release_version, release_tuple


class ManifestVersionContractTest(unittest.TestCase):
    def test_stable_release_version_is_accepted(self):
        self.assertEqual(release_tuple("1.7.32"), (1, 7, 32))
        self.assertTrue(is_valid_release_version("1.7.32"))

    def test_prerelease_version_is_accepted_as_numeric_release(self):
        self.assertEqual(release_tuple("1.7.32b11"), (1, 7, 32))
        self.assertTrue(is_valid_release_version("1.7.32b11"))

    def test_release_thresholds_reject_lower_versions(self):
        cases = (
            ("1.5.4", "1.5.3", (1, 5, 4)),
            ("1.5.6", "1.5.5", (1, 5, 6)),
            ("1.5.7", "1.5.6", (1, 5, 7)),
        )
        for equal_version, lower_version, threshold in cases:
            with self.subTest(threshold=threshold):
                self.assertGreaterEqual(release_tuple(equal_version), threshold)
                self.assertLess(release_tuple(lower_version), threshold)

    def test_suffix_does_not_raise_numeric_release(self):
        self.assertLess(release_tuple("1.7.31b9"), (1, 7, 32))
        self.assertGreaterEqual(release_tuple("1.7.32b11"), (1, 7, 32))
        self.assertLess(release_tuple("1.7.32b11"), (1, 7, 33))

    def test_lower_prerelease_does_not_pass_higher_threshold(self):
        self.assertLess(release_tuple("1.7.31b9"), (1, 7, 32))

    def test_malformed_versions_are_rejected(self):
        for value in ("1.7", "1.7.32.4", "abc", "", "1..32"):
            with self.subTest(value=value):
                self.assertFalse(is_valid_release_version(value))
                with self.assertRaises(ValueError):
                    release_tuple(value)


if __name__ == "__main__":
    unittest.main()
