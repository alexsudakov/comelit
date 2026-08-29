import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sanitize_c_source.py"
spec = importlib.util.spec_from_file_location("sanitize_c_source", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class SanitizeCSourceTests(unittest.TestCase):
    def test_comments_and_string_values_are_removed(self):
        source = '''
// secret endpoint https://example.invalid/path
static int probe(const char *token) {
    const char *url = "https://example.invalid/abc";
    const char *json = "{\\\"message\\\":\\\"access\\\",\\\"user-token\\\":\\\"SECRET\\\"}\\n";
    return token != 0 ? 1 : 0; /* private comment */
}
'''
        sanitized, counts, string_count = module.sanitize_c_source(source)
        self.assertEqual(string_count, 2)
        self.assertNotIn("example.invalid", sanitized)
        self.assertNotIn("SECRET", sanitized)
        self.assertNotIn("private comment", sanitized)
        self.assertIn("static int probe", sanitized)
        self.assertGreaterEqual(counts["message"], 1)
        self.assertGreaterEqual(counts["access"], 1)
        self.assertGreaterEqual(counts["user-token"], 1)

    def test_line_count_is_preserved_for_comments(self):
        source = "int a;\n/* one\ntwo */\nint b;\n"
        sanitized, _, _ = module.sanitize_c_source(source)
        self.assertEqual(source.count("\n"), sanitized.count("\n"))

    def test_comment_redaction_does_not_leave_trailing_whitespace(self):
        source = "int a;  // comment\n    /* block\n       comment */\nint b;\t\n"
        sanitized, _, _ = module.sanitize_c_source(source)
        self.assertEqual(source.count("\n"), sanitized.count("\n"))
        for line in sanitized.splitlines():
            self.assertEqual(line, line.rstrip(" \t"))

    def test_safe_control_char_literals_can_remain(self):
        source = "int f(void) { return '\\n' == '\\n'; }\n"
        sanitized, _, _ = module.sanitize_c_source(source)
        self.assertIn("'\\n'", sanitized)

    def test_function_discovery_keeps_identifiers(self):
        source = '''
static gboolean vip_send_access(App *app, int channel_id) {
    return TRUE;
}
void teardown(void) {
}
'''
        sanitized, _, _ = module.sanitize_c_source(source)
        self.assertEqual(module.discover_function_names(sanitized), ["teardown", "vip_send_access"])


if __name__ == "__main__":
    unittest.main()
