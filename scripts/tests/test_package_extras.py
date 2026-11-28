import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("package_extras", SCRIPTS / "package_extras.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def minimal_sources(root):
    (root / "README.md").write_text("Public README")
    (root / "LICENSE").write_text("Public license")
    for name in module.SOURCE_ROOTS:
        (root / name).mkdir()


class PackageExtrasTests(unittest.TestCase):
    def test_probe_and_screenshot_claims_exclude_private_outputs(self):
        probe = module.ARTIFACTS["apps2sd_probe"]
        illumination = module.ARTIFACTS["illumination"]
        self.assertEqual(probe["certificate_sha256"], illumination["certificate_sha256"])
        self.assertTrue(probe["validation_scope"]["only_this_probe_apk_symlink_verified"])
        self.assertTrue(probe["validation_scope"]["generated_private_storage_module_is_not_packaged"])
        screenshot = module.ARTIFACTS["screenshot_overlay"]["validation_scope"]
        self.assertTrue(screenshot["actual_screenshot_png_saved"])
        self.assertTrue(screenshot["media_store_image_row_created"])
        self.assertEqual(screenshot["saved_png_bytes"], 47318)
        self.assertNotIn("media_store_id", screenshot)
        self.assertNotIn("filename", screenshot)

    def test_private_audit_is_outside_the_explicit_source_roots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            minimal_sources(root)
            audit = root / ".local-audit"
            audit.mkdir()
            (audit / "userdata-test.img").write_bytes(b"private")
            names = {name for name, _ in module.public_sources(root)}
            self.assertEqual(names, {"README.md", "LICENSE"})

    def test_a_generated_identity_configuration_in_module_source_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            minimal_sources(root)
            (root / "modules" / "identity.conf").write_text("private storage identity")
            with self.assertRaises(ValueError):
                module.public_sources(root)

    def test_a_photo_or_device_log_inside_public_source_is_not_silently_packaged(self):
        for name in ("screen.png", "device.txt"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                minimal_sources(root)
                (root / "tools" / name).write_bytes(b"private")
                with self.assertRaises(ValueError):
                    module.public_sources(root)

    def test_cached_bytecode_is_not_packaged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            minimal_sources(root)
            cache = root / "scripts" / "__pycache__"
            cache.mkdir()
            (cache / "old.pyc").write_bytes(b"cache")
            names = {name for name, _ in module.public_sources(root)}
            self.assertNotIn("scripts/__pycache__/old.pyc", names)

    def test_stage_does_not_build_a_source_zip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "repo"
            repo.mkdir()
            minimal_sources(repo)
            source = root / "public.apk"
            source.write_bytes(b"checked source")
            artifacts = {"sample": {"name": "public.apk", "sha256": module.digest(source),
                                     "certificate_sha256": None, "validation_scope": {"checked": True}}}
            destination = root / "stage"
            with patch.object(module, "REPO", repo), patch.object(module, "ARTIFACTS", artifacts), \
                    patch.object(module, "verify_artifacts"):
                plan = module.stage(destination, {"sample": source}, None)
            self.assertFalse((destination / module.ZIP_NAME).exists())
            self.assertEqual((destination / "public.apk").read_bytes(), source.read_bytes())
            self.assertIn("not sealed", plan["status"])

    def test_existing_stage_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "keep.txt").write_text("user")
            with self.assertRaises(FileExistsError):
                module.stage(root, {}, None)
            self.assertEqual((root / "keep.txt").read_text(), "user")

    def test_seal_recollects_source_changes_after_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "repo"
            repo.mkdir()
            minimal_sources(repo)
            source = root / "public.apk"
            source.write_bytes(b"checked source")
            artifacts = {"sample": {"name": "public.apk", "sha256": module.digest(source),
                                     "certificate_sha256": None, "validation_scope": {"checked": True}}}
            destination = root / "stage"
            with patch.object(module, "REPO", repo), patch.object(module, "ARTIFACTS", artifacts), \
                    patch.object(module, "verify_artifacts"):
                module.stage(destination, {"sample": source}, None)
                (repo / "README.md").write_text("Final source after readiness")
                result = module.seal(destination, None)
            snapshot = json.loads((destination / "SOURCE-MANIFEST.json").read_text())
            entry = next(entry for entry in snapshot["files"] if entry["name"] == "README.md")
            self.assertEqual(entry["sha256"], module.digest(repo / "README.md"))
            self.assertFalse(result["main_rom_rebuilt"])


if __name__ == "__main__":
    unittest.main()
