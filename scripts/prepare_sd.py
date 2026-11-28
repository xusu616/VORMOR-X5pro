#!/usr/bin/env python3
"""Create new, empty SD-backed Android 10 data/cache files on the host.

This never formats an SD card or touches a connected Android device. Existing
images are refused. Copy the generated files to the SD FAT32 partition later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

MIB = 1024 * 1024
FAT32_MAX_BYTES = 0xFFFFFFFF
EXT4_FEATURES = (
    "has_journal", "ext_attr", "resize_inode", "dir_index", "filetype",
    "extent", "flex_bg", "sparse_super", "large_file", "huge_file",
    "dir_nlink", "extra_isize",
)
IMAGE_NAMES = ("userdata-test.img", "cache-test.img")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(MIB), b""):
            digest.update(chunk)
    return digest.hexdigest()


def linux_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return str(resolved)
    if not resolved.drive or len(resolved.drive) != 2:
        raise ValueError("WSL inputs must use a local Windows drive, not a UNC path")
    return "/mnt/" + resolved.drive[0].lower() + resolved.as_posix()[2:]


class E2fsTools:
    def __init__(self, distro: str | None = None):
        self.distro = distro

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        command = args
        if os.name == "nt":
            if not self.distro:
                raise ValueError("On Windows, supply --wsl-distro with e2fsprogs installed")
            command = ["wsl.exe", "--distribution", self.distro, "--", *args]
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        if result.returncode:
            raise RuntimeError(f"{args[0]} failed ({result.returncode}):\n"
                               + result.stdout + result.stderr)
        return result


def check_new_outputs(directory: Path) -> None:
    if directory.is_symlink():
        raise ValueError("The output directory must not be a symbolic link")
    if directory.exists() and not directory.is_dir():
        raise ValueError("The output path is not a directory")
    for name in (*IMAGE_NAMES, "sd-images.json"):
        target = directory / name
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Refusing to overwrite {target}")


def create_image(path: Path, byte_count: int, label: str, tools: E2fsTools) -> dict:
    if byte_count <= 0 or byte_count > FAT32_MAX_BYTES or byte_count % 4096:
        raise ValueError("Image length must be 4K-aligned and fit a FAT32 file")
    filesystem_uuid = str(uuid.uuid4())
    # Exclusive creation also closes a race after the output-directory check.
    with path.open("xb") as stream:
        stream.truncate(byte_count)
    features = "none," + ",".join(EXT4_FEATURES)
    tools.run([
        "mke2fs", "-t", "ext4", "-F", "-q", "-b", "4096", "-I", "256",
        "-L", label, "-U", filesystem_uuid, "-O", features,
        "-E", "lazy_itable_init=0,lazy_journal_init=0,root_owner=0:0",
        linux_path(path),
    ])
    tools.run(["e2fsck", "-f", "-n", linux_path(path)])
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "filesystem": "ext4",
        "uuid": filesystem_uuid,
        "features": list(EXT4_FEATURES),
        "block_size": 4096,
        "inode_size": 256,
        "contains_user_data": False,
        "contains_adb_authorization_keys": False,
        "contains_nvdata_clone": False,
        "read_only_fsck_passed": True,
    }


def prepare(directory: Path, data_mib: int, cache_mib: int, tools: E2fsTools) -> dict:
    if data_mib < 2048:
        raise ValueError("Use at least the validated 2048 MiB userdata size")
    if cache_mib < 128:
        raise ValueError("Use at least the validated 128 MiB cache size")
    if max(data_mib, cache_mib) * MIB > FAT32_MAX_BYTES:
        raise ValueError("An individual image cannot exceed FAT32's file-size limit")
    check_new_outputs(directory)
    tools.run(["mke2fs", "-V"])
    directory.mkdir(parents=True, exist_ok=True)
    images = [
        create_image(directory / IMAGE_NAMES[0], data_mib * MIB, "a10-trial-data", tools),
        create_image(directory / IMAGE_NAMES[1], cache_mib * MIB, "a10-trial-cache", tools),
    ]
    result = {
        "format": "vormor-a10-sd-images-v1",
        "images": images,
        "sd_destination": "/external_sd/.codex-android10-test/",
        "first_boot": "Authorize your own ADB host on screen; no author's keys are included",
        "device_access_performed": False,
        "sd_card_formatted": False,
    }
    with (directory / "sd-images.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--data-mib", type=int, default=2048)
    parser.add_argument("--cache-mib", type=int, default=128)
    parser.add_argument("--wsl-distro", help="Windows only: existing WSL distribution with e2fsprogs")
    args = parser.parse_args()
    try:
        result = prepare(args.output_dir.absolute(), args.data_mib, args.cache_mib,
                         E2fsTools(args.wsl_distro))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Stopped: {error}\nAny newly created partial images are preserved; "
              "inspect them or choose a different new output directory.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
