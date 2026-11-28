import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("edit_bcb", SCRIPTS / "edit_bcb.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class EditBcbTests(unittest.TestCase):
    def test_recovery_command_preserves_the_other_480_bytes(self):
        before = bytes(32) + bytes(range(256)) + bytes(range(224))
        after = module.edit(before, True)
        self.assertEqual(after[:32], b"boot-recovery".ljust(32, b"\0"))
        self.assertEqual(after[32:], before[32:])

    def test_recovery_roundtrip_back_to_normal_preserves_payload(self):
        before = bytes(32) + bytes(range(256)) + bytes(range(224))
        self.assertEqual(module.edit(module.edit(before, True), False), before)

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / "before.bin", root / "after.bin"
            source.write_bytes(bytes(512))
            target.write_bytes(b"user")
            argv = ["edit_bcb.py", "--input", str(source), "--output", str(target), "--recovery"]
            with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(module.main(), 1)
            self.assertEqual(target.read_bytes(), b"user")
            self.assertEqual(source.read_bytes(), bytes(512))

    def test_short_capture_is_refused(self):
        with self.assertRaises(module.InstallError):
            module.edit(b"short", True)


if __name__ == "__main__":
    unittest.main()
