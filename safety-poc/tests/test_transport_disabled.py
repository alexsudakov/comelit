import tempfile
import unittest
from pathlib import Path

from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import State
from comelit_safety_poc.store import Journal
from comelit_safety_poc.transport import DisabledRealTransport


class DisabledTransportTests(unittest.TestCase):
    def test_real_backend_is_fail_closed_and_no_network_exists(self):
        with tempfile.TemporaryDirectory() as td:
            j = Journal(Path(td) / "state.sqlite3")
            ex = OneShotExecutor(j, DisabledRealTransport(), Policy(0))
            op = ex.execute(operation_id="disabled-1", target="door-a")
            self.assertEqual(op.state, State.FAILED_SAFE)
            self.assertIn("intentionally not implemented", op.detail)


if __name__ == "__main__":
    unittest.main()
