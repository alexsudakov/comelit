import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
SOURCE = ROOT / "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA_DIR / "entrance_self_activation_signaling_transform.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_self_activation_signaling_transform_escaping",
    TRANSFORM,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P33EntranceSignalingGeneratedCEscaping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text(encoding="utf-8")
        cls.candidate = module.transform(source)

    def test_registration_status_strings_keep_c_newline_escapes(self):
        required = (
            'printf("ENTRANCE_SIGNALING_ARMED=true\\n");',
            'printf("ENTRANCE_SIGNALING_WAIT_FOR_PSEUDOTCP_OPEN=true\\n");',
            'printf("ENTRANCE_SIGNALING_CTPP_REUSE_REQUIRED=true\\n");',
            'printf("ENTRANCE_SIGNALING_SECOND_CTPP_OPEN=false\\n");',
            'fprintf(stderr, "ENTRANCE_SIGNALING_TIMER_START=FAIL\\n");',
        )
        for statement in required:
            self.assertIn(statement, self.candidate)

    def test_registration_status_strings_do_not_contain_literal_newlines(self):
        bad = (
            'printf("ENTRANCE_SIGNALING_ARMED=true\n");',
            'printf("ENTRANCE_SIGNALING_WAIT_FOR_PSEUDOTCP_OPEN=true\n");',
            'printf("ENTRANCE_SIGNALING_CTPP_REUSE_REQUIRED=true\n");',
            'printf("ENTRANCE_SIGNALING_SECOND_CTPP_OPEN=false\n");',
            'fprintf(stderr, "ENTRANCE_SIGNALING_TIMER_START=FAIL\n");',
        )
        for statement in bad:
            self.assertNotIn(statement, self.candidate)


if __name__ == "__main__":
    unittest.main()
