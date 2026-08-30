from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_p13_runtime_artifacts.sh"


class P13InstallScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_install_creates_expected_paths_and_modes(self):
        self.assertIn("NATIVE_DIR=/root/comelit-p13-native", self.text)
        self.assertIn('HOLDER="$NATIVE_DIR/comelit_p13_holder"', self.text)
        self.assertIn("WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper", self.text)
        self.assertIn('chmod 700 "$HOLDER"', self.text)
        self.assertIn('chown root:root "$HOLDER"', self.text)
        self.assertIn('chmod 700 "$WRAPPER"', self.text)
        self.assertIn('chown root:root "$WRAPPER"', self.text)
        self.assertIn('chmod 700 "$NATIVE_DIR"', self.text)

    def test_install_is_non_actuating(self):
        self.assertIn("P13_INSTALL_NON_ACTUATING=true", self.text)
        self.assertIn("SEND_ARMED_REACHED=false", self.text)
        self.assertIn("P13_NETWORK_ACTION_PERFORMED=false", self.text)
        self.assertIn("P13_UAUT_CTPP_ACTION_PERFORMED=false", self.text)
        self.assertIn("P13_DOOR_ACTION_PERFORMED=false", self.text)
        for forbidden in ("curl ", "wget ", "open_door", "systemctl start"):
            self.assertNotIn(forbidden, self.text)

    def test_install_requires_root_and_exact_identity(self):
        self.assertIn("P13_INSTALL_REQUIRES_ROOT=true", self.text)
        self.assertIn("P13_INSTALL_REMOTE_IDENTITY=FAIL", self.text)
        self.assertIn('git -C "$REPO_ROOT" rev-parse "origin/$EXPECTED_BRANCH"', self.text)
        self.assertIn("P13_INSTALL_BRANCH=FAIL", self.text)
        self.assertIn("P13_INSTALL_WORKTREE_DIRTY=true", self.text)

    def test_install_pins_baseline_holder(self):
        self.assertIn("P13_BASE_SOURCE_PIN=FAIL", self.text)
        self.assertIn("P13_BASE_BINARY_PIN=FAIL", self.text)
        self.assertIn("d8c3bd50c33d702699b96c24f08363bb06f3b5312b3033aceead9ed67a6ce9d9", self.text)
        self.assertIn("628b9c020bd3948d5edae2b7a6d68061c8af2b3a72e26463f2f5486f1e61d9de", self.text)

    def test_install_runs_transform_and_compiles(self):
        self.assertIn("p13_holder_transform.py", self.text)
        self.assertIn("--source \"$BASE_SOURCE\"", self.text)
        self.assertIn("--payload \"$PAYLOAD\"", self.text)
        self.assertIn("--output \"$HOLDER_SOURCE\"", self.text)
        self.assertIn('cc -O2 -Wall -Wextra', self.text)
        self.assertIn("pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0", self.text)

    def test_install_validates_holder_markers_statically(self):
        self.assertIn("strings -a \"$HOLDER\" | grep -q 'P13_CTPP_OPEN_OUTCOME'", self.text)
        self.assertIn("strings -a \"$HOLDER\" | grep -q 'P13_DOOR_WRITE_COUNT'", self.text)
        self.assertIn("strings -a \"$HOLDER\" | grep -q 'P13_TEARDOWN=PASS'", self.text)
        self.assertIn("P13_HOLDER_BUILD=PASS", self.text)

    def test_install_binds_wrapper_to_holder(self):
        self.assertIn("P13_WRAPPER_HOLDER_BIND=FAIL", self.text)
        self.assertIn("P13_WRAPPER_TEMPLATE_MARKER_REMAINS=true", self.text)
        self.assertIn("P13_WRAPPER_INSTALL=PASS", self.text)

    def test_install_preserves_payload_readonly(self):
        self.assertIn("PAYLOAD_MODE=\"$(stat -c '%a' \"$PAYLOAD\")\"", self.text)
        self.assertIn('[[ "$PAYLOAD_MODE" == "600" ]]', self.text)
        # payload must not be written by the install
        self.assertNotIn("chmod 600 \"$PAYLOAD\"", self.text)


if __name__ == "__main__":
    unittest.main()
