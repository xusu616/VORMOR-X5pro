import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "configure_apps2sd_external_mount.py"
SPEC = importlib.util.spec_from_file_location("configure_apps2sd_external_mount", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExternalConfigurationTests(unittest.TestCase):
    def test_configuration_uses_the_application_owned_sqlite_database(self):
        # aes(context) passes "apps2sd.db" to SQLiteOpenHelper. Editing the
        # native exported apps2sdpro.db snapshot is lost on the next app run.
        self.assertEqual(MODULE.DATABASE,
                         "/data/data/in.co.pricealert.apps2sd/databases/apps2sd.db")
        self.assertNotEqual(MODULE.DATABASE, "/data/apps2sd/apps2sdpro.db")

    def test_only_two_mount_preferences_change(self):
        raw = (b'<map><string name="language">zh_CN</string>'
               b'<int name="saved_counter" value="12" />'
               b'<boolean name="disable_auto_mount" value="false" /></map>')
        before = MODULE.preference_map(raw)
        after = MODULE.preference_map(MODULE.update_preferences(raw))
        self.assertEqual(after["language"], before["language"])
        self.assertEqual(after["saved_counter"], before["saved_counter"])
        self.assertEqual(after["disable_auto_mount"][1]["value"], "true")
        self.assertEqual(after["auto_soft_reboot"][1]["value"], "false")

    def test_duplicate_or_wrong_type_preferences_stop(self):
        with self.assertRaises(MODULE.ConfigurationError):
            MODULE.update_preferences(b'<map><string name="auto_soft_reboot">x</string></map>')
        with self.assertRaises(MODULE.ConfigurationError):
            MODULE.update_preferences(b'<map><int name="x" value="1"/><int name="x" value="2"/></map>')

    def test_different_existing_filesystem_rows_are_not_overwritten(self):
        self.assertTrue(MODULE.validate_rows([]))
        self.assertFalse(MODULE.validate_rows([MODULE.EXPECTED_ROW]))
        with self.assertRaises(MODULE.ConfigurationError):
            MODULE.validate_rows([("mmcblk1", "/dev/block/mmcblk1p2", "", "ext4", "", "")])
        with self.assertRaises(MODULE.ConfigurationError):
            MODULE.validate_rows([MODULE.EXPECTED_ROW, MODULE.EXPECTED_ROW])

    def test_queries_open_database_read_only_without_remote_mutations(self):
        class FakeAdb:
            def shell(self, command):
                self.command = command
                return "ok"
        adb = FakeAdb()
        self.assertEqual(MODULE.sql_query(adb, "PRAGMA integrity_check;"), "ok")
        self.assertIn("?mode=ro", adb.command)
        for mutation in (".backup", "INSERT", "UPDATE", "DELETE", "mkdir", "push", "force-stop"):
            self.assertNotIn(mutation, adb.command)


if __name__ == "__main__":
    unittest.main()
