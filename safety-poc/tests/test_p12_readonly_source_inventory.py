import importlib.util
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "p12_readonly_source_inventory.py"
spec = importlib.util.spec_from_file_location("p12_readonly_source_inventory", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class P12ReadonlySourceInventoryTests(unittest.TestCase):
    def test_qualified_method_shape_redacts_non_timeout_literals(self):
        source = '''
class Client:
    async def connect(self, host):
        secret = "TOP-SECRET-ENDPOINT"
        await asyncio.wait_for(worker(), timeout=3.5)
        return secret
'''
        shape = module.method_shape(source, "Client", "connect")
        rendered = "\n".join(module.render_shape(shape))
        self.assertIn("METHOD=Client.connect", rendered)
        self.assertIn("WAIT_FOR_TIMEOUT_VALUES=3.5", rendered)
        self.assertNotIn("TOP-SECRET-ENDPOINT", rendered)

    def test_top_level_readonly_wrapper_is_distinct_from_class_method(self):
        source = '''
class Client:
    async def list_doors(self):
        return []

async def list_doors(host, token):
    client = Client()
    await client.connect()
    await client.authenticate(token)
    return await client.list_doors()
'''
        class_shape = module.method_shape(source, "Client", "list_doors")
        wrapper_shape = module.top_level_function_shape(source, "list_doors")
        self.assertEqual(class_shape.qualified_name, "Client.list_doors")
        self.assertEqual(wrapper_shape.qualified_name, "module.list_doors")
        calls = dict(wrapper_shape.call_counts)
        self.assertEqual(calls["client.connect"], 1)
        self.assertEqual(calls["client.authenticate"], 1)
        self.assertEqual(calls["client.list_doors"], 1)

    def test_dynamic_timeout_is_redacted(self):
        source = '''
class Client:
    async def connect(self, timeout):
        await asyncio.wait_for(worker(), timeout=timeout)
'''
        shape = module.method_shape(source, "Client", "connect")
        self.assertEqual(shape.timeout_values, ("dynamic_or_redacted",))


if __name__ == "__main__":
    unittest.main()
