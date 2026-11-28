import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

MODULE_PATH = Path(__file__).resolve().parents[1] / "flash_android10.py"
SPEC = importlib.util.spec_from_file_location("flash_android10", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def valid_gpt():
    raw = bytearray(34 * 512)
    entries = bytearray(128 * 128)
    for name, (index, offset, length) in module.EXPECTED_PARTITIONS.items():
        entry = bytearray(128)
        entry[:16] = bytes(range(1, 17))
        entry[16:32] = bytes(range(17, 33))
        struct.pack_into("<QQ", entry, 32, offset // 512, (offset + length) // 512 - 1)
        encoded = name.encode("utf-16-le")
        entry[56:56 + len(encoded)] = encoded
        entries[(index - 1) * 128:index * 128] = entry
    raw[1024:1024 + len(entries)] = entries
    header = bytearray(512)
    header[:8] = b"EFI PART"
    struct.pack_into("<III", header, 8, 0x10000, 92, 0)
    struct.pack_into("<QIII", header, 72, 2, 128, 128, zlib.crc32(entries) & 0xFFFFFFFF)
    struct.pack_into("<I", header, 16, zlib.crc32(header[:92]) & 0xFFFFFFFF)
    raw[512:1024] = header
    return bytes(raw)


class FlashTests(unittest.TestCase):
    def test_valid_reference_gpt_is_accepted(self):
        parsed = module.parse_gpt(valid_gpt())
        self.assertEqual(parsed["system"], module.EXPECTED_PARTITIONS["system"])

    def test_modified_gpt_header_is_refused(self):
        raw = bytearray(valid_gpt())
        raw[512 + 32] ^= 1
        with self.assertRaises(module.InstallError):
            module.parse_gpt(bytes(raw))

    def test_corrupt_partition_table_is_refused(self):
        raw = bytearray(valid_gpt())
        raw[1024 + 32] ^= 1
        with self.assertRaises(module.InstallError):
            module.parse_gpt(bytes(raw))

    def test_another_valid_gpt_layout_is_not_flashed(self):
        raw = bytearray(valid_gpt())
        offset = 1024 + (8 - 1) * 128 + 32
        struct.pack_into("<Q", raw, offset, 1)
        entries = raw[1024:34 * 512]
        struct.pack_into("<I", raw, 512 + 88, zlib.crc32(entries) & 0xFFFFFFFF)
        header = bytearray(raw[512:512 + 92])
        header[16:20] = bytes(4)
        struct.pack_into("<I", raw, 512 + 16, zlib.crc32(header) & 0xFFFFFFFF)
        with self.assertRaises(module.InstallError):
            module.parse_gpt(bytes(raw))

    def test_normal_bcb_changes_only_command(self):
        for command in (b"", b"boot-recovery", b"bootonce-bootloader"):
            before = command.ljust(32, b"\0") + bytes(range(256)) + bytes(range(224))
            result = module.normal_bcb(before)
            self.assertEqual(len(result), 512)
            self.assertEqual(result[:32], bytes(32))
            self.assertEqual(result[32:], before[32:])

    def test_corrupt_bcb_length_and_unknown_command_are_refused(self):
        for raw in (b"short", b"unexpected".ljust(512, b"\0")):
            with self.assertRaises(module.InstallError):
                module.normal_bcb(raw)

    def test_manifest_traversal_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = {"name": "../private.img", "bytes": 1, "sha256": "0" * 64}
            with self.assertRaises(module.InstallError):
                module.manifest_image(Path(directory), entry, 1)

    def test_modified_local_image_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "boot.img"
            image.write_bytes(b"modified")
            entry = {"name": image.name, "bytes": 8, "sha256": hashlib.sha256(b"original").hexdigest()}
            with self.assertRaises(module.InstallError):
                module.manifest_image(root, entry, 8)

    def test_existing_result_directory_preserves_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keep.txt").write_text("user")
            with self.assertRaises(module.InstallError):
                module.new_result_directory(root)
            self.assertEqual((root / "keep.txt").read_text(), "user")

    def test_backup_of_another_device_is_refused_before_image_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backup-manifest.json").write_text(json.dumps({
                "format": "vormor-a10-backup-v1", "serial": "OTHER", "images": {},
            }))
            with self.assertRaises(module.InstallError):
                module.read_backups(root, "CURRENT")

    def test_default_plan_never_invokes_mutations(self):
        argv = ["flash_android10.py", "--serial", "TEST", "--rom-dir", "unused"]
        device = {"twrp": "3.2.1-0", "mounts": "", "gpt": {}}
        with patch.object(sys, "argv", argv), patch.object(module, "read_rom", return_value=({}, {})), \
                patch.object(module, "check_device", return_value=device), \
                patch.object(module, "flash_pair") as flash, \
                patch.object(module, "write_normal_boot") as bcb, \
                patch.object(module, "create_backup") as backup, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(), 0)
            flash.assert_not_called()
            bcb.assert_not_called()
            backup.assert_not_called()

    def test_flash_requires_explicit_backup_and_board_ack_before_device_access(self):
        argv = ["flash_android10.py", "--serial", "TEST", "--flash", "--rom-dir", "unused"]
        with patch.object(sys, "argv", argv), patch.object(module, "Adb") as adb, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(module.main(), 1)
            adb.assert_not_called()

    def test_mounted_platform_aliases_are_detected(self):
        mounts = ("/dev/block/platform/x/by-name/system /system ext4 ro 0 0\n"
                  "/dev/block/mmcblk0p23 /data ext4 rw 0 0\n"
                  "/dev/block/loop7 /tmp/test ext4 ro 0 0")
        self.assertEqual(len(module.mounted_originals(mounts)), 2)


if __name__ == "__main__":
    unittest.main()
