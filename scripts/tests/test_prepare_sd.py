import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "prepare_sd.py"
SPEC = importlib.util.spec_from_file_location("prepare_sd", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class PrepareSdTests(unittest.TestCase):
    def test_existing_user_image_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            image = directory / "userdata-test.img"
            image.write_bytes(b"existing user content")
            with self.assertRaises(FileExistsError):
                module.check_new_outputs(directory)
            self.assertEqual(image.read_bytes(), b"existing user content")

    def test_existing_cache_or_manifest_also_blocks_creation(self):
        for name in ("cache-test.img", "sd-images.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                (directory / name).write_bytes(b"keep")
                with self.assertRaises(FileExistsError):
                    module.check_new_outputs(directory)

    def test_non_directory_output_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file"
            path.write_text("keep")
            with self.assertRaises(ValueError):
                module.check_new_outputs(path)
            self.assertEqual(path.read_text(), "keep")

    def test_old_kernel_incompatible_features_are_excluded(self):
        for feature in ("64bit", "metadata_csum", "metadata_csum_seed", "orphan_file", "encrypt", "verity"):
            self.assertNotIn(feature, module.EXT4_FEATURES)

    def test_invalid_lengths_fail_before_creating_files(self):
        class NoTools:
            def run(self, args):
                self.fail("No subprocess should run")
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "new"
            for size in (0, 4097, 0x100000000):
                with self.subTest(size=size), self.assertRaises(ValueError):
                    module.create_image(directory / "userdata-test.img", size, "data", NoTools())
            self.assertFalse(directory.exists())

    def test_invalid_sd_sizes_fail_before_tool_or_directory_mutation(self):
        class NoTools:
            def run(self, args):
                raise AssertionError("No subprocess should run")
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "new"
            for data, cache in ((1024, 128), (2048, 64), (4096, 128)):
                with self.subTest(data=data, cache=cache), self.assertRaises(ValueError):
                    module.prepare(directory, data, cache, NoTools())
            self.assertFalse(directory.exists())


if __name__ == "__main__":
    unittest.main()
