import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

PATH = Path(__file__).resolve().parents[1] / "build_apps2sd_mount_module.py"
SPEC = importlib.util.spec_from_file_location("build_apps2sd_mount_module", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MountModuleTests(unittest.TestCase):
    def identity(self):
        return MODULE.validate_identity("a" * 32, 2048, 4096, 8192,
                                        "f27ff45d-55dc-4b37-93bd-b8efdb35f7e1")

    def test_external_identity_rejects_shell_injection_and_invalid_geometry(self):
        with self.assertRaises(ValueError):
            MODULE.validate_identity("a" * 31 + ";", 1, 1, 8,
                                     "f27ff45d-55dc-4b37-93bd-b8efdb35f7e1")
        with self.assertRaises(ValueError):
            MODULE.validate_identity("a" * 32, 2048, 8192, 8192,
                                     "f27ff45d-55dc-4b37-93bd-b8efdb35f7e1")
        with self.assertRaises(ValueError):
            MODULE.validate_identity("a" * 32, 1, 1, 8,
                                     "00000000-0000-0000-0000-000000000000")

    def test_all_identity_checks_precede_the_only_setrw_and_mount(self):
        script = MODULE.POST_FS_DATA
        change = script.index('/system/bin/blockdev --setrw "$PARTITION"')
        for required in ("SD CID mismatch", "SD capacity mismatch", "p3 start sector mismatch",
                         "p3 length mismatch", "p3 UUID mismatch", "p3 is not ext4",
                         "p3 is already mounted elsewhere", "Expected isolated loop7 /data"):
            self.assertLess(script.index(required), change)
        self.assertEqual(script.count("--setrw"), 1)
        self.assertIn("PARTITION=/dev/block/mmcblk1p3", script)
        for forbidden in ("mkfs", "mke2fs", "fsck", "reboot", "--setrw /dev/block/mmcblk0",
                          "while true", "sleep ", "cp /data", "pm clear", "uninstall"):
            self.assertNotIn(forbidden, script)

    def test_uuid_mismatch_does_not_silently_accept_old_media(self):
        self.assertIn('[ "$actual_uuid" = "$EXPECTED_UUID" ] || fail', MODULE.POST_FS_DATA)
        self.assertIn("sys.apps2sd.mount_state blocked", MODULE.POST_FS_DATA)
        self.assertIn("--setro", MODULE.POST_FS_DATA)

    def test_fresh_ext4_root_is_labeled_after_mount_before_ready(self):
        script = MODULE.POST_FS_DATA
        mounted = script.index('mount_owned=1')
        label = script.index('/system/bin/restorecon "$MOUNTPOINT"', mounted)
        ready = script.index('/system/bin/setprop sys.apps2sd.mount_state ready')
        self.assertLess(mounted, label)
        self.assertLess(label, ready)
        self.assertNotIn('restorecon -R', script)

    def test_generated_archive_preserves_executable_modes_and_explicit_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "module"
            archive = MODULE.generate(output, self.identity())
            with zipfile.ZipFile(archive) as z:
                self.assertIn("post-fs-data.sh", z.namelist())
                self.assertNotIn("service.sh", z.namelist())
                self.assertEqual((z.getinfo("post-fs-data.sh").external_attr >> 16) & 0o777,
                                 0o755)
                self.assertIn(self.identity()["uuid"].encode(), z.read("identity.conf"))
                self.assertEqual(z.testzip(), None)
            with self.assertRaises(FileExistsError):
                MODULE.generate(output, self.identity())

    def test_invalid_installer_stops_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer = root / "installer"
            installer.write_text("unexpected")
            output = root / "module"
            with self.assertRaises(ValueError):
                MODULE.generate(output, self.identity(), installer)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
