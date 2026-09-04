import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ComelitOAuthRefreshRuntimeTests(unittest.TestCase):
    def test_p2p_http_status_is_classified_before_json_decode(self):
        source = (ROOT / "custom_components/comelit/cloud.py").read_text()
        self.assertLess(
            source.index("if not 200 <= status < 300:"),
            source.index("obj = json.loads"),
        )
        self.assertIn("raise ComelitCloudHttpError(status)", source)

    def test_refresh_scope_is_persisted_not_hardcoded(self):
        source = (ROOT / "custom_components/comelit/oauth.py").read_text()
        self.assertIn("CONF_OAUTH_SCOPE", source)
        self.assertIn('fields["scope"] = scope', source)
        self.assertIn("scope=scope", source)
        self.assertNotIn('SCOPE = "all"', source)

    def test_runtime_has_exactly_two_p2p_bootstrap_calls_and_no_retry_loop(self):
        source = (ROOT / "custom_components/comelit/runtime.py").read_text()
        tree = ast.parse(source)
        cycle = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_async_run_cycle"
        )
        p2p_calls = [
            node
            for node in ast.walk(cycle)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "async_negotiate_p2p"
        ]
        self.assertEqual(len(p2p_calls), 2)
        self.assertEqual(
            [node for node in ast.walk(cycle) if isinstance(node, ast.While)], []
        )
        self.assertIn("if exc.status != 401", source)
        self.assertIn("force_refresh=True", source)


if __name__ == "__main__":
    unittest.main()
