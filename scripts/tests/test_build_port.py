"""Host-only regressions for the public build inputs and output boundaries."""
from pathlib import Path
import hashlib
import io
import lzma
import os
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_port


def sparse_image(chunks, blocks, checksum=0, minor=0):
    header = struct.pack("<I4H4I", build_port.SPARSE_MAGIC, 1, minor, 28, 12, 4,
                         blocks, len(chunks), checksum)
    return header + b"".join(struct.pack("<2H2I", kind, 0, count, 12 + len(payload)) + payload
                             for kind, count, payload in chunks)


def newc(name, content=b"", mode=0o100644, uid=0, gid=0):
    name = name.encode() + b"\0"
    fields = [1, mode, uid, gid, 1, 0, len(content), 0, 0, 0, 0, len(name), 0]
    data = b"070701" + b"".join(f"{field:08x}".encode() for field in fields) + name
    data += b"\0" * (-len(data) % 4)
    data += content
    return data + b"\0" * (-len(data) % 4)


class SparseTests(unittest.TestCase):
    def convert(self, data, limit=1024):
        output = io.BytesIO()
        size = build_port.convert_sparse(io.BytesIO(data), output, limit)
        self.assertEqual(size, len(output.getvalue()))
        return output.getvalue()

    def test_all_chunk_types_and_crc_including_zero_holes(self):
        expected = b"ABCD" + b"\x01\x23\x45\x67" * 2 + b"\0" * 4
        crc = zlib.crc32(expected)
        data = sparse_image([(0xCAC1, 1, b"ABCD"), (0xCAC2, 2, b"\x01\x23\x45\x67"),
                             (0xCAC3, 1, b""), (0xCAC4, 0, struct.pack("<I", crc))], 4, crc)
        self.assertEqual(self.convert(data), expected)

    def test_truncated_raw_payload_is_rejected(self):
        data = sparse_image([(0xCAC1, 1, b"ABCD")], 1)
        with self.assertRaisesRegex(build_port.BuildError, "Truncated"):
            self.convert(data[:-1])

    def test_declared_output_and_chunk_dimensions_are_checked(self):
        for data in (sparse_image([(0xCAC1, 1, b"ABCD")], 2),
                     sparse_image([(0xCAC1, 2, b"ABCD")], 2),
                     sparse_image([(0xCAC2, 1, b"ABCDextra")], 1)):
            with self.subTest(data=data), self.assertRaises(build_port.BuildError):
                self.convert(data)

    def test_crc_mismatch_unknown_chunk_and_trailing_data_are_rejected(self):
        valid = sparse_image([(0xCAC1, 1, b"ABCD")], 1)
        for data in (sparse_image([(0xCAC1, 1, b"ABCD")], 1, 1),
                     sparse_image([(0xCAC1, 1, b"ABCD"), (0xCAC4, 0, b"\0" * 4)], 1),
                     sparse_image([(0xFFFF, 1, b"ABCD")], 1), valid + b"extra"):
            with self.subTest(data=data), self.assertRaises(build_port.BuildError):
                self.convert(data)

    def test_capacity_is_checked_before_writing(self):
        output = io.BytesIO()
        with self.assertRaisesRegex(build_port.BuildError, "capacity"):
            build_port.convert_sparse(io.BytesIO(sparse_image([(0xCAC3, 10, b"")], 10)), output, 8)
        self.assertEqual(output.getvalue(), b"")

    def test_supported_major_can_have_new_minor(self):
        self.assertEqual(self.convert(sparse_image([(0xCAC1, 1, b"ABCD")], 1, minor=1)), b"ABCD")


class InputAndOutputTests(unittest.TestCase):
    def test_insufficient_space_stops_before_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new-output"
            with mock.patch.object(build_port.shutil, "disk_usage", return_value=SimpleNamespace(free=1)):
                with self.assertRaisesRegex(build_port.BuildError, "free bytes"):
                    build_port.check_disk_space(output, 1024)
            self.assertFalse(output.exists())

    def test_xz_sparse_conversion_streams_and_checks_both_representations(self):
        expected = b"ABCD" + b"\0" * 4
        sparse = sparse_image([(0xCAC1, 1, b"ABCD"), (0xCAC3, 1, b"")], 2)
        profile = {"system_partition_bytes": 1024, "phh_system": {
            "sparse_sha256": hashlib.sha256(sparse).hexdigest(),
            "raw_sha256": hashlib.sha256(expected).hexdigest(), "raw_bytes": len(expected)}}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.img.xz"
            source.write_bytes(lzma.compress(sparse))
            target = Path(directory) / "output.img"
            build_port.stock_raw(source, "xz", target, profile)
            self.assertEqual(target.read_bytes(), expected)
            self.assertFalse((Path(directory) / "stock-sparse.img").exists())
            profile["phh_system"]["sparse_sha256"] = "0" * 64
            with self.assertRaisesRegex(build_port.BuildError, "sparse source SHA-256"):
                build_port.stock_raw(source, "xz", Path(directory) / "bad-output.img", profile)
    def test_hash_mismatch_does_not_change_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.img"
            source.write_bytes(b"original input")
            build_port.check_hash(source, hashlib.sha256(source.read_bytes()).hexdigest())
            with self.assertRaisesRegex(build_port.BuildError, "SHA-256 mismatch"):
                build_port.check_hash(source, "0" * 64)
            self.assertEqual(source.read_bytes(), b"original input")

    def test_bad_base_stops_before_output_creation_or_tool_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "wrong-boot.img"
            source.write_bytes(b"wrong device")
            output = folder / "output"
            args = SimpleNamespace(configs=build_port.CONFIGS, base_boot=source, vendor_cil=None,
                                   magiskboot=folder / "tool", magiskboot_sha256=None, output_dir=output)
            with mock.patch.object(build_port, "run_tool") as tool:
                with self.assertRaisesRegex(build_port.BuildError, "SHA-256 mismatch"):
                    build_port.build_boot(args)
                tool.assert_not_called()
            self.assertFalse(output.exists())

    def test_wrong_optional_systemui_stops_before_output_or_linux_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "source.img"
            source.write_bytes(b"source handled by the source-validator fixture")
            apk = folder / "wrong.apk"
            apk.write_bytes(b"untrusted replacement")
            output = folder / "output"
            args = SimpleNamespace(configs=build_port.CONFIGS, phh_system=source,
                                   systemui_apk=apk, output_dir=output)
            with mock.patch.object(build_port, "classify_system", return_value="raw"):
                with mock.patch.object(build_port.LinuxTools, "run") as tools:
                    with self.assertRaisesRegex(build_port.BuildError, "SHA-256 mismatch"):
                        build_port.build_system(args)
                    tools.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(apk.read_bytes(), b"untrusted replacement")

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.mkdir()
            user_file = output / "keep.txt"
            user_file.write_text("user data")
            with self.assertRaisesRegex(build_port.BuildError, "new directory"):
                build_port.reserve_output(output)
            self.assertEqual(user_file.read_text(), "user data")

    def test_dangling_output_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            try:
                output.symlink_to(Path(directory) / "missing", target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Host cannot create a test symlink: {error}")
            with self.assertRaises(build_port.BuildError):
                build_port.reserve_output(output)
            self.assertTrue(output.is_symlink())

    def test_debugfs_quote_cannot_inject_another_command(self):
        self.assertEqual(build_port.debugfs_quote('/path with "quote"'), '"/path with \\"quote\\""')
        with self.assertRaises(build_port.BuildError):
            build_port.debugfs_quote("/file\nrm /another-file")

    def test_config_payload_cannot_escape_its_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(build_port.BuildError):
                build_port.config_file(Path(directory), "../private.img")

    def test_overlay_names_cannot_escape_native_windows_staging(self):
        for name in ("../private", "..\\..\\private", "C:/private", "C:\\private",
                     "/private", "directory/../private", ".", "directory/./file"):
            with self.subTest(name=name), self.assertRaises(build_port.BuildError):
                build_port.validate_member_name(name)


class CpioAndPublicConfigTests(unittest.TestCase):
    def test_cpio_retains_member_type_owner_and_contents(self):
        data = newc("directory", mode=0o040755, uid=1000, gid=2000)
        data += newc("directory/file", b"payload", uid=1000, gid=2000)
        data += newc("TRAILER!!!")
        parsed = build_port.cpio_members(data)
        self.assertEqual(parsed["directory"], (0o040755, 1000, 2000, b""))
        self.assertEqual(parsed["directory/file"], (0o100644, 1000, 2000, b"payload"))

    def test_duplicate_traversal_and_truncated_cpio_are_rejected(self):
        for data in (newc("same") + newc("same") + newc("TRAILER!!!"),
                     newc("../private") + newc("TRAILER!!!"),
                     newc("file", b"payload")[:-2]):
            with self.subTest(data=data), self.assertRaises(build_port.BuildError):
                build_port.cpio_members(data)

    def test_public_helper_uses_runtime_owner_and_protects_present_p3(self):
        build_port.load_configs(build_port.CONFIGS)
        helper = (build_port.CONFIGS / "ramdisk/android10-prepare-test.sh").read_text()
        self.assertNotRegex(helper, r"(?m)^expected_owner=[^$\n]+$")
        self.assertGreater(helper.index("device_serial=$(/system/bin/getprop ro.boot.serialno)"),
                           helper.index("\nfail() {"))
        self.assertIn('[ -n "$device_serial" ] || fail', helper)
        self.assertIn("expected_owner=$device_serial:mmcblk0p16:v1", helper)
        block = helper.split("if [ -b /dev/block/mmcblk1p3 ]; then\n", 1)[1].split("\nfi", 1)[0]
        self.assertIn("blockdev --setro /dev/block/mmcblk1p3 || fail", block)
        self.assertLess(len('/mnt/vendor/a10-test/.codex-android10-test/userdata-test.img'), 64)


if __name__ == "__main__":
    unittest.main()
