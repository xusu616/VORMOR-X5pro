#!/usr/bin/env python3
"""Stage explicit public Extras assets, then seal only with an explicit --seal.

This packages host files only. No device, Git, or publishing commands run.
The staging step deliberately leaves the source ZIP unbuilt so ongoing source
changes can be reviewed before the final --seal command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import zipfile

from package_release import add_file, digest

REPO = Path(__file__).resolve().parent.parent
SOURCE_ROOTS = ("docs", "scripts", "configs", "modules", "apps", "overlays", "tools")
SOURCE_SUFFIXES = {".md", ".py", ".ps1", ".json", ".xml", ".kt", ".sh", ".html", ".so", ".rc"}
SOURCE_PLAIN_NAMES = {"sepolicy", "module.prop", "skip_mount", "update-binary", "updater-script", "fstab.android10-trial"}
SOURCE_EXACT_PATHS = {"configs/ramdisk/.backup/.magisk"}
EXCLUDED_PARTS = {".git", ".local-audit", "__pycache__", ".gradle", "build", "dist"}
FORBIDDEN_NAMES = {"identity.conf", "adb_keys", "userdata.img", "userdata-test.img", "cache-test.img",
                   "nvram.img", "nvdata.img", "para-before.bin", "bcb-before.bin", "action.log", "mount.log"}
ZIP_NAME = "VORMOR-X5pro-Android10-beta1-Extras.zip"
STAGE_OWNER = {"format": "vormor-extras-stage-v1", "owner": "host-package-extras"}

ARTIFACTS = {
    "camera": {
        "name": "Camera2-M19X6-rear-preview180.apk",
        "sha256": "48c8ce73270bdbc5bf54c8fa9f85430ed6e61b9ffe5ca8e4c43b25ff5eb6147a",
        "certificate_sha256": "a40da80a59d170caa950cf15c18c454d47a39b26989d8b640ecd745ba71bf5dc",
        "validation_scope": {
            "pinned_phh_v222_source_apk": True,
            "change": "CaptureModule.updatePreviewTransform adds centered postRotate180 only for BACK",
            "front_and_jpeg_direction_methods_unchanged": True,
            "user_confirmed_front_and_back_preview": True,
            "not_verified": ["all-app HAL orientation", "all video/landscape/focus paths"],
            "included_in_base_rom": False,
        },
    },
    "screenshot_overlay": {
        "name": "SystemUI-M19X6-small-width-overlay.apk",
        "sha256": "c554f09b7cb271c398207327997dd53159ae65f769e7f4c7c77f959f4368b802",
        "certificate_sha256": "c8a2e9bccf597c2fb6dc66bee293fc13f2fc47ec77bc6b2b0d52c11f51192ab8",
        "validation_scope": {
            "change": "11 missing default dimensions use existing sw288dp baseline",
            "device_overlay_and_power_menu_observed": True,
            "screenshot_menu_entry_observed": True,
            "actual_screenshot_png_saved": True,
            "saved_png_bytes": 47318,
            "media_store_image_row_created": True,
            "private_screenshot_file_and_media_identity_excluded": True,
            "included_in_base_rom": False,
        },
    },
    "illumination": {
        "name": "M19X6-Illumination-1.1.apk",
        "sha256": "143f85cb8f9447bd34ae8e0c22b4c3f0fe48e34e33ebd97e23fbb86046399b58",
        "certificate_sha256": "a40da80a59d170caa950cf15c18c454d47a39b26989d8b640ecd745ba71bf5dc",
        "validation_scope": {
            "kotlin_build_and_api29_signature_verified": True,
            "legacy_camera1_torch_channel": True,
            "device_tile_off_on_off_and_driver_enable_disable_verified": True,
            "user_confirmed_switch_fixed": True,
            "requires_camera_permission": True,
            "camera1_is_occupied_while_enabled": True,
            "included_in_base_rom": False,
        },
    },
    "magisk": {
        "name": "Magisk-v30.6.apk",
        "sha256": "f1ffc3c9a5614c251ba6bada308163acc3c3d844cf01d33f55a8bc151adc34ce",
        "certificate_sha256": None,
        "validation_scope": {
            "source": "Official topjohnwu/Magisk v30.6 release asset",
            "official_release_digest_previously_verified": True,
            "unmodified_apk": True,
            "not_a_latest_version_claim": True,
            "manager_environment_and_module_setup": "Follow README; preserve adapted boot and application data",
        },
    },
    "apps2sd_probe": {
        "name": "M19X6-Apps2SD-Link-Probe-1.0.apk",
        "sha256": "3e735812440048c6ff4080381815285fe628839c6dcf4e4a5e79138990b8c9c3",
        "certificate_sha256": "a40da80a59d170caa950cf15c18c454d47a39b26989d8b640ecd745ba71bf5dc",
        "validation_scope": {
            "package": "xusu616.vormor.apps2sdprobe",
            "kotlin_build_and_api29_signature_verified": True,
            "only_this_probe_apk_symlink_verified": True,
            "normal_reboot_and_launch_counts_1_2_3_verified": True,
            "probe_own_file_contents_and_hash_preserved": True,
            "not_verified": ["other installed applications", "moving application data/dex/native libraries"],
            "identity_specific_mount_module_must_be_generated_by_each_owner": True,
            "generated_private_storage_module_is_not_packaged": True,
            "included_in_base_rom": False,
        },
    },
}


def scan_public_input(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Not a regular public input: {path.name}")
    if path.name in FORBIDDEN_NAMES:
        raise ValueError(f"Private or generated filename is not publishable: {path.name}")
    raw = path.read_bytes()
    # Concrete author-device serial form and embedded private key blocks must
    # never enter a supposedly portable source package or APK asset.
    if re.search(rb"BBH[0-9A-Z]{14,}", raw):
        raise ValueError(f"Personal device serial found in {path.name}")
    if re.search(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----", raw):
        raise ValueError(f"Embedded private key found in {path.name}")
    if re.search(rb"(?m)^\s*EXPECTED_(?:CID|UUID)\s*=\s*['\"]?[0-9a-fA-F]{8,}", raw):
        raise ValueError(f"Generated personal storage identity found in {path.name}")


def public_sources(root: Path) -> list[tuple[str, Path]]:
    inputs = []
    for name in ("README.md", "LICENSE"):
        path = root / name
        scan_public_input(path)
        inputs.append((name, path))
    for directory in SOURCE_ROOTS:
        parent = root / directory
        if parent.is_symlink():
            raise ValueError(f"Public source root is a symbolic link: {directory}")
        if not parent.is_dir():
            raise ValueError(f"Required source directory is absent: {directory}")
        for path in sorted(parent.rglob("*")):
            relative = path.relative_to(root)
            if set(relative.parts) & EXCLUDED_PARTS or path.suffix in {".pyc", ".log"}:
                continue
            if path.is_symlink():
                raise ValueError(f"Symbolic source input refused: {relative.as_posix()}")
            if not path.is_file():
                continue
            if (path.suffix not in SOURCE_SUFFIXES and path.name not in SOURCE_PLAIN_NAMES
                    and relative.as_posix() not in SOURCE_EXACT_PATHS):
                raise ValueError(f"Unexpected file inside a public source root: {relative.as_posix()}")
            scan_public_input(path)
            inputs.append((relative.as_posix(), path))
    names = [name for name, _ in inputs]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate public archive paths")
    return inputs


def source_scope(name: str) -> str:
    if name.startswith("configs/"):
        return "Pinned public port inputs; public boot adaptations host validated, not directly flashed"
    if name.startswith("modules/"):
        return "Optional Magisk-only module source; target-specific layout and daemon behavior documented"
    if name.startswith("apps/apps2sd-link-probe/") or "apps2sd" in name:
        return "Host generator or separate probe source; no author's SD identity, generated module or application data"
    if name.startswith("apps/illumination/"):
        return "Illumination v1.1 source matching the independent device-tested APK"
    if name.startswith("overlays/"):
        return "No-code SystemUI small-width resource overlay source"
    if name.startswith("tools/"):
        return "Diagnostic source only; no generated device outputs or logs"
    return "Documentation or host source; scope and remaining device verification are stated in README"


def source_manifest(inputs: list[tuple[str, Path]]) -> dict:
    return {
        "format": "vormor-extras-sources-v1",
        "files": [{"name": name, "bytes": path.stat().st_size, "sha256": digest(path),
                   "validation_scope": source_scope(name)} for name, path in inputs],
        "no_private_audits_or_device_outputs": True,
    }


def verify_artifacts(paths: dict[str, Path], apksigner: Path | None) -> None:
    for key, metadata in ARTIFACTS.items():
        path = paths[key]
        scan_public_input(path)
        if digest(path) != metadata["sha256"]:
            raise ValueError(f"Pinned APK digest mismatch: {metadata['name']}")
        with zipfile.ZipFile(path) as apk:
            if apk.testzip() is not None or "AndroidManifest.xml" not in apk.namelist():
                raise ValueError(f"APK ZIP CRC/manifest check failed: {metadata['name']}")
        if apksigner:
            result = subprocess.run([str(apksigner), "verify", "--min-sdk-version", "29",
                                     "--print-certs", str(path)], capture_output=True, text=True)
            if result.returncode:
                raise ValueError(f"API29 APK signature check failed: {metadata['name']}")
            expected_cert = metadata["certificate_sha256"]
            if expected_cert and expected_cert not in result.stdout.lower():
                raise ValueError(f"APK certificate differs from the checked ROM key: {metadata['name']}")


def stage(output: Path, paths: dict[str, Path], apksigner: Path | None) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("Use a new Extras staging directory")
    verify_artifacts(paths, apksigner)
    sources = public_sources(REPO)
    output.mkdir(parents=True, exist_ok=False)
    (output / ".stage-owner.json").write_text(json.dumps(STAGE_OWNER) + "\n", encoding="utf-8")
    for key, source in paths.items():
        destination = output / ARTIFACTS[key]["name"]
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst, 1048576)
        if digest(destination) != ARTIFACTS[key]["sha256"]:
            raise ValueError("Staged asset copy does not match the pinned source")
    plan = {
        "format": "vormor-extras-plan-v1", "status": "staged; source ZIP deliberately not sealed",
        "planned_zip": ZIP_NAME,
        "artifacts": [{"name": data["name"], "sha256": data["sha256"],
                       "validation_scope": data["validation_scope"]} for data in ARTIFACTS.values()],
        "source_snapshot": source_manifest(sources),
        "final_source_collection": "Recollect immediately before --seal after source readiness confirmation",
        "main_rom_rebuilt": False,
    }
    (output / "staging-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def seal(output: Path, apksigner: Path | None) -> dict:
    owner = json.loads((output / ".stage-owner.json").read_text(encoding="utf-8"))
    if owner != STAGE_OWNER or output.is_symlink():
        raise ValueError("Only the explicit owned Extras staging directory may be sealed")
    targets = (ZIP_NAME, "extras-manifest.json", "SHA256SUMS-extras", "SOURCE-MANIFEST.json")
    if any((output / name).exists() or (output / name).is_symlink() for name in targets):
        raise FileExistsError("An existing sealed or partial Extras output will not be overwritten")
    paths = {key: output / data["name"] for key, data in ARTIFACTS.items()}
    verify_artifacts(paths, apksigner)
    inputs = public_sources(REPO)
    snapshot = source_manifest(inputs)
    source_info = output / "SOURCE-MANIFEST.json"
    source_info.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    archive = output / ZIP_NAME
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, source in inputs:
            executable = source.suffix in {".py", ".sh"} or source.name == "update-binary"
            add_file(z, source, name, executable)
        add_file(z, source_info, "SOURCE-MANIFEST.json")
    with zipfile.ZipFile(archive) as z:
        expected = {entry["name"]: entry for entry in snapshot["files"]}
        if set(z.namelist()) != set(expected) | {"SOURCE-MANIFEST.json"} or z.testzip() is not None:
            raise ValueError("Extras archive list/CRC check failed")
        for name, entry in expected.items():
            raw = z.read(name)
            if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError(f"Source changed during sealing or ZIP content mismatched: {name}")
    assets = []
    for key, data in ARTIFACTS.items():
        path = paths[key]
        assets.append({"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path),
                       "certificate_sha256": data["certificate_sha256"],
                       "validation_scope": data["validation_scope"]})
    assets.append({"name": archive.name, "bytes": archive.stat().st_size, "sha256": digest(archive),
                   "validation_scope": {"source_list_and_all_payload_hashes_verified": True,
                                        "zip_crc_verified": True, "source_files": len(inputs)}})
    result = {
        "format": "vormor-android10-extras-v1", "base_release": "android10-beta1-20261128",
        "status": "host sealed and verified; not uploaded by this script",
        "assets": assets, "source_manifest_inside_zip": "SOURCE-MANIFEST.json",
        "main_rom_rebuilt": False, "main_rom_images_unchanged": True,
        "public_boot_adaptations": "Host-only validation as stated in the base ROM README",
        "storage_module_scope": "Each owner generates their own identity-conf/module; no private generated module is included",
        "excluded": [".local-audit", "device identities", "SD images", "nvdata clones",
                     "private keys", "ADB authorization", "photos", "screenshots", "device logs"],
    }
    manifest_path = output / "extras-manifest.json"
    manifest_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    public_files = [*paths.values(), archive, manifest_path]
    (output / "SHA256SUMS-extras").write_text(
        "".join(digest(path) + "  " + path.name + "\n" for path in sorted(public_files)), encoding="ascii")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apksigner", type=Path)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--stage", action="store_true", help="Copy the five checked public APKs; hold the source ZIP")
    actions.add_argument("--seal", action="store_true", help="Explicitly seal only after current source is ready")
    for key in ARTIFACTS:
        parser.add_argument("--" + key.replace("_", "-"), type=Path)
    args = parser.parse_args()
    if args.stage:
        paths = {key: getattr(args, key) for key in ARTIFACTS}
        if any(path is None for path in paths.values()):
            parser.error("--stage requires camera, screenshot-overlay, illumination, magisk and apps2sd-probe paths")
        result = stage(args.output_dir, paths, args.apksigner)
    else:
        result = seal(args.output_dir, args.apksigner)
    print(json.dumps({"status": result["status"], "main_rom_rebuilt": False}, indent=2))


if __name__ == "__main__":
    main()
