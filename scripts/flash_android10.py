#!/usr/bin/env python3
"""Plan, back up, and explicitly flash the checked M19_X6 Android 10 pair.

All device access goes through the normal ADB executable. The default is a
read-only plan. --flash writes only boot/system and --normal-boot changes only
the first 32 bytes of a freshly captured para sector. No userdata formatting,
package removal, or automatic device reboot is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import zlib

MIB = 1024 * 1024
SECTOR = 512
EXPECTED_PARTITIONS = {
    "boot": (8, 0x1D80000, 0x1000000),
    "recovery": (9, 0x2D80000, 0x1000000),
    "para": (10, 0x3D80000, 0x80000),
    "vendor": (14, 0x6000000, 0x19800000),
    "nvdata": (16, 0x1F900000, 0x2000000),
    "system": (21, 0x25000000, 0x146800000),
    "cache": (22, 0x16B800000, 0x7000000),
    "userdata": (23, 0x172800000, 0x5CF80000),
}
BOOT_BYTES = 16777216
SYSTEM_BYTES = 1131864064
ROM_STAGE = "/external_sd/.codex-rom-install"
SD_IMAGES = "/external_sd/.codex-android10-test"


class InstallError(Exception):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(MIB), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_image(directory: Path, entry: dict, expected_bytes: int) -> Path:
    name = entry.get("name", "")
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise InstallError("Manifest image names must be plain file names")
    expected_sha = entry.get("sha256", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha):
        raise InstallError(f"Invalid manifest SHA-256 for {name}")
    if entry.get("bytes") != expected_bytes:
        raise InstallError(f"Unexpected image length in manifest: {name}")
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise InstallError(f"Image is missing or is a symbolic link: {path}")
    if path.stat().st_size != expected_bytes or sha256(path) != expected_sha.lower():
        raise InstallError(f"Image length/SHA-256 does not match: {path}")
    return path


def read_rom(directory: Path, manifest: Path) -> tuple[dict, dict[str, Path]]:
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("format") != "vormor-a10-rom-v1":
        raise InstallError("Unsupported ROM manifest format")
    images = metadata.get("images", {})
    if set(images) != {"boot", "system"}:
        raise InstallError("The ROM manifest must contain exactly boot and system")
    paths = {
        "boot": manifest_image(directory, images["boot"], BOOT_BYTES),
        "system": manifest_image(directory, images["system"], SYSTEM_BYTES),
    }
    return metadata, paths


def parse_gpt(raw: bytes) -> dict[str, tuple[int, int, int]]:
    if len(raw) < 2 * SECTOR:
        raise InstallError("GPT read was incomplete")
    header = raw[SECTOR:2 * SECTOR]
    if header[:8] != b"EFI PART":
        raise InstallError("No primary GPT header was found")
    header_size, expected_crc = struct.unpack_from("<II", header, 12)
    if not 92 <= header_size <= SECTOR:
        raise InstallError("Invalid GPT header length")
    check = bytearray(header[:header_size])
    check[16:20] = bytes(4)
    if zlib.crc32(check) & 0xFFFFFFFF != expected_crc:
        raise InstallError("Primary GPT header CRC mismatch")
    entries_lba, count, entry_bytes, entries_crc = struct.unpack_from("<QIII", header, 72)
    if count < 25 or entry_bytes < 128 or entry_bytes % 8:
        raise InstallError("Unsupported GPT entry geometry")
    offset = entries_lba * SECTOR
    length = count * entry_bytes
    if offset + length > len(raw):
        raise InstallError("GPT entries exceed the captured 34 sectors")
    entries = raw[offset:offset + length]
    if zlib.crc32(entries) & 0xFFFFFFFF != entries_crc:
        raise InstallError("GPT partition entries CRC mismatch")
    found = {}
    for index in range(count):
        entry = entries[index * entry_bytes:(index + 1) * entry_bytes]
        if not any(entry[:16]):
            continue
        first, last = struct.unpack_from("<QQ", entry, 32)
        name = entry[56:128].decode("utf-16-le").split("\0", 1)[0]
        if name in found or last < first:
            raise InstallError("Duplicated or invalid GPT partition entry")
        found[name] = (index + 1, first * SECTOR, (last - first + 1) * SECTOR)
    for name, expected in EXPECTED_PARTITIONS.items():
        if found.get(name) != expected:
            raise InstallError(f"Unsupported partition layout for {name}: {found.get(name)}")
    return found


def normal_bcb(raw: bytes) -> bytes:
    if len(raw) != SECTOR:
        raise InstallError(f"Expected a 512-byte BCB sector, got {len(raw)}")
    command = raw[:32].split(b"\0", 1)[0]
    if command not in (b"", b"boot-recovery", b"bootonce-bootloader"):
        raise InstallError(f"Unexpected existing BCB command: {command!r}")
    return bytes(32) + raw[32:]


def new_result_directory(directory: Path) -> None:
    if directory.exists() or directory.is_symlink():
        raise InstallError(f"Result directory already exists: {directory}")
    directory.mkdir(parents=True)


class Adb:
    def __init__(self, executable: str, serial: str):
        self.prefix = [executable, "-s", serial]
        self.serial = serial

    def run(self, *args: str) -> bytes:
        result = subprocess.run([*self.prefix, *args], capture_output=True)
        if result.returncode:
            raise InstallError(result.stderr.decode(errors="replace")
                               + result.stdout.decode(errors="replace"))
        return result.stdout

    def shell(self, command: str) -> str:
        return self.run("shell", command).decode("utf-8", errors="replace").replace("\r", "").strip()

    def capture(self, command: str) -> bytes:
        return self.run("exec-out", command)

    def stream_partition(self, node: str, output: Path, expected_bytes: int) -> None:
        with output.open("xb") as stream:
            result = subprocess.run([
                *self.prefix, "exec-out",
                f"dd if={shlex.quote(node)} bs=1048576 2>/dev/null",
            ], stdout=stream, stderr=subprocess.PIPE)
        if result.returncode or output.stat().st_size != expected_bytes:
            raise InstallError(f"Incomplete partition snapshot: {output}\n"
                               + result.stderr.decode(errors="replace"))

    def push(self, source: Path, target: str) -> None:
        self.run("push", str(source), target)

    def remote_sha(self, path: str, length: int | None = None) -> str:
        command = f"sha256sum {shlex.quote(path)}"
        if length is not None:
            command = f"head -c {length} {shlex.quote(path)} | sha256sum"
        result = self.shell(command).split()
        if not result or not re.fullmatch(r"[0-9a-fA-F]{64}", result[0]):
            raise InstallError(f"Could not read remote SHA-256 for {path}")
        return result[0].lower()


def check_device(adb: Adb) -> dict:
    state = adb.run("get-state").decode().strip()
    if state != "recovery":
        raise InstallError(f"Expected TWRP recovery, ADB state is {state}")
    version = adb.shell("getprop ro.twrp.version")
    if not version.startswith("3.2.1-0"):
        raise InstallError(f"Only the checked TWRP 3.2.1-0 profile is supported, got {version!r}")
    gpt = adb.capture("dd if=/dev/block/mmcblk0 bs=512 count=34 2>/dev/null")
    partitions = parse_gpt(gpt)
    for name in ("boot", "para", "system", "cache", "userdata"):
        index, _, length = partitions[name]
        reported = adb.shell(f"cat /sys/block/mmcblk0/mmcblk0p{index}/size")
        if reported != str(length // SECTOR):
            raise InstallError(f"Kernel block-device size differs from GPT for {name}")
    mounts = adb.shell("cat /proc/mounts")
    return {"twrp": version, "gpt": partitions, "mounts": mounts}


def mounted_originals(mounts: str) -> list[str]:
    aliases = {"mmcblk0p8", "boot", "mmcblk0p21", "system",
               "mmcblk0p22", "cache", "mmcblk0p23", "userdata"}
    return [line for line in mounts.splitlines()
            if line.split() and line.split()[0].rsplit("/", 1)[-1] in aliases]


def create_backup(adb: Adb, directory: Path, device: dict) -> dict:
    busy = mounted_originals(device["mounts"])
    if busy:
        raise InstallError("Unmount the original boot/system/data/cache volumes in TWRP first:\n"
                           + "\n".join(busy))
    new_result_directory(directory)
    entries = {}
    for name in ("boot", "system"):
        index, _, length = EXPECTED_PARTITIONS[name]
        node = f"/dev/block/mmcblk0p{index}"
        path = directory / f"{name}-before.img"
        before = adb.remote_sha(node)
        adb.stream_partition(node, path, length)
        after = adb.remote_sha(node)
        local = sha256(path)
        if before != local or after != local:
            raise InstallError(f"Backup was not stable and verified: {name}")
        entries[name] = {"name": path.name, "bytes": length, "sha256": local}
        print(f"Verified private backup: {name}", flush=True)
    metadata = {"format": "vormor-a10-backup-v1", "serial": adb.serial, "images": entries}
    (directory / "backup-manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def read_backups(directory: Path, serial: str) -> dict:
    metadata = json.loads((directory / "backup-manifest.json").read_text(encoding="utf-8"))
    if metadata.get("format") != "vormor-a10-backup-v1" or metadata.get("serial") != serial:
        raise InstallError("Backup manifest belongs to a different device or unsupported format")
    images = metadata.get("images", {})
    if set(images) != {"boot", "system"}:
        raise InstallError("Both full boot and system backups are required")
    for name in ("boot", "system"):
        manifest_image(directory, images[name], EXPECTED_PARTITIONS[name][2])
    return metadata


def read_sd_images(directory: Path) -> tuple[dict, dict[str, Path]]:
    metadata = json.loads((directory / "sd-images.json").read_text(encoding="utf-8"))
    if metadata.get("format") != "vormor-a10-sd-images-v1":
        raise InstallError("Use new images generated by prepare_sd.py")
    entries = {entry["name"]: entry for entry in metadata.get("images", [])}
    if set(entries) != {"userdata-test.img", "cache-test.img"}:
        raise InstallError("Both blank trial data/cache images are required")
    images = {}
    for name, minimum in (("userdata-test.img", 2048 * MIB), ("cache-test.img", 128 * MIB)):
        entry = entries[name]
        length = entry.get("bytes", 0)
        if not isinstance(length, int) or length < minimum or length > 0xFFFFFFFF or length % 4096:
            raise InstallError(f"Invalid trial image length: {name}")
        for flag in ("contains_user_data", "contains_adb_authorization_keys", "contains_nvdata_clone"):
            if entry.get(flag) is not False:
                raise InstallError(f"Trial image is not declared freshly empty: {name}")
        images[name] = manifest_image(directory, entry, length)
    return metadata, images


def check_unused_sd_paths(adb: Adb) -> None:
    paths = [f"{SD_IMAGES}/userdata-test.img", f"{SD_IMAGES}/cache-test.img",
             f"{ROM_STAGE}/boot.img", f"{ROM_STAGE}/system.img"]
    conditions = " || ".join(f"test -e {shlex.quote(path)}" for path in paths)
    result = adb.shell(f"if {conditions}; then echo occupied; else echo empty; fi")
    if result != "empty":
        raise InstallError("Existing trial/staging images found on SD; they will not be overwritten")
    if adb.shell("test -d /external_sd && echo present") != "present":
        raise InstallError("TWRP /external_sd is not available")
    mounts = adb.shell("cat /proc/mounts")
    if not any(len(line.split()) >= 4 and line.split()[1] == "/external_sd"
               and line.split()[2] == "vfat" and "rw" in line.split()[3].split(",")
               for line in mounts.splitlines()):
        raise InstallError("The public SD first partition must be mounted RW as vfat at /external_sd")


def write_normal_boot(adb: Adb, results: Path) -> dict:
    before = adb.capture("dd if=/dev/block/mmcblk0p10 bs=512 count=1 2>/dev/null")
    after = normal_bcb(before)
    (results / "bcb-before.bin").write_bytes(before)
    local = results / "bcb-normal.bin"
    local.write_bytes(after)
    remote = "/tmp/vormor-a10-normal-bcb.bin"
    adb.push(local, remote)
    if adb.remote_sha(remote) != hashlib.sha256(after).hexdigest():
        raise InstallError("BCB upload hash mismatch; no BCB write performed")
    adb.shell(f"set -e; dd if={remote} of=/dev/block/mmcblk0p10 bs=512 count=1 conv=notrunc; sync")
    observed = adb.capture("dd if=/dev/block/mmcblk0p10 bs=512 count=1 2>/dev/null")
    (results / "bcb-normal-readback.bin").write_bytes(observed)
    if observed != after:
        raise InstallError("BCB exact readback mismatch; do not reboot")
    return {"old_command": before[:32].split(b"\0", 1)[0].decode(),
            "only_command_32_changed": after[32:] == before[32:],
            "readback_verified": True}


def flash_pair(adb: Adb, rom: dict, images: dict[str, Path], sd: dict,
               sd_paths: dict[str, Path], backups: dict, device: dict, results: Path) -> dict:
    busy = mounted_originals(device["mounts"])
    if busy:
        raise InstallError("Unmount original boot/system/data/cache in TWRP before --flash:\n"
                           + "\n".join(busy))
    check_unused_sd_paths(adb)
    # A backup of some other firmware/device is insufficient. The currently
    # unmounted source partitions must match this user's verified backups.
    for name in ("boot", "system"):
        node = f"/dev/block/mmcblk0p{EXPECTED_PARTITIONS[name][0]}"
        if adb.remote_sha(node) != backups["images"][name]["sha256"].lower():
            raise InstallError(f"Current {name} differs from the supplied own-device backup")
    new_result_directory(results)
    adb.shell(f"set -e; mkdir -p {SD_IMAGES} {ROM_STAGE}")
    upload_entries = []
    for name in ("userdata-test.img", "cache-test.img"):
        remote = f"{SD_IMAGES}/{name}"
        adb.push(sd_paths[name], remote)
        expected = next(entry["sha256"] for entry in sd["images"] if entry["name"] == name)
        if adb.remote_sha(remote) != expected.lower():
            raise InstallError(f"SD image upload mismatch: {name}; partitions have not been written")
        upload_entries.append(name)
    for name in ("boot", "system"):
        remote = f"{ROM_STAGE}/{name}.img"
        adb.push(images[name], remote)
        if adb.remote_sha(remote) != rom["images"][name]["sha256"].lower():
            raise InstallError(f"ROM upload mismatch: {name}; partitions have not been written")
    for name in ("system", "boot"):
        index = EXPECTED_PARTITIONS[name][0]
        adb.shell(f"set -e; dd if={ROM_STAGE}/{name}.img of=/dev/block/mmcblk0p{index} bs=1048576; sync")
        expected = rom["images"][name]
        if adb.remote_sha(f"/dev/block/mmcblk0p{index}", expected["bytes"]) != expected["sha256"].lower():
            raise InstallError(f"{name} partition readback mismatch; leave the device in recovery")
        print(f"Flashed and readback verified: {name}", flush=True)
    bcb = write_normal_boot(adb, results)
    result = {"format": "vormor-a10-install-result-v1", "serial": adb.serial,
              "boot_system_readback_verified": True, "bcb": bcb,
              "new_sd_images": upload_entries, "original_userdata_formatted": False,
              "original_cache_formatted": False, "device_rebooted": False}
    (results / "install-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--adb", default="adb", help="Normal Android platform-tools ADB executable")
    cli.add_argument("--serial", required=True, help="The explicitly selected ADB serial")
    cli.add_argument("--rom-dir", type=Path, help="Extracted ROM release containing boot.img and system.img")
    cli.add_argument("--manifest", type=Path, help="Defaults to ROM directory's rom-manifest.json")
    cli.add_argument("--sd-images-dir", type=Path, help="Fresh files produced by prepare_sd.py")
    cli.add_argument("--backup-dir", type=Path, help="Private full boot/system snapshots with backup-manifest.json")
    cli.add_argument("--result-dir", type=Path, help="A new private result directory, required for writes")
    actions = cli.add_mutually_exclusive_group()
    actions.add_argument("--flash", action="store_true", help="Explicitly write the checked boot/system pair")
    actions.add_argument("--create-backup", type=Path, metavar="NEW_DIR", help="Read-only capture of current boot/system")
    actions.add_argument("--normal-boot", action="store_true", help="Only clear para's recovery command with readback")
    cli.add_argument("--ack-m19-x6", action="store_true", help="Acknowledge physical board/vendor compatibility checked separately")
    return cli


def main() -> int:
    args = parser().parse_args()
    try:
        if args.flash and (not args.ack_m19_x6 or not args.rom_dir or not args.sd_images_dir
                           or not args.backup_dir or not args.result_dir):
            raise InstallError("--flash requires --ack-m19-x6, --rom-dir, --sd-images-dir, --backup-dir and --result-dir")
        if args.normal_boot and not args.result_dir:
            raise InstallError("--normal-boot requires a new --result-dir")
        rom, images = ({}, {})
        if args.rom_dir:
            rom, images = read_rom(args.rom_dir, args.manifest or args.rom_dir / "rom-manifest.json")
        elif not (args.create_backup or args.normal_boot):
            raise InstallError("Supply --rom-dir for the read-only plan")
        sd, sd_paths = read_sd_images(args.sd_images_dir) if args.sd_images_dir else ({}, {})
        backups = read_backups(args.backup_dir, args.serial) if args.backup_dir else {}
        adb = Adb(args.adb, args.serial)
        device = check_device(adb)
        if args.create_backup:
            result = create_backup(adb, args.create_backup, device)
        elif args.normal_boot:
            new_result_directory(args.result_dir)
            result = write_normal_boot(adb, args.result_dir)
        elif args.flash:
            result = flash_pair(adb, rom, images, sd, sd_paths, backups, device, args.result_dir)
        else:
            result = {"mode": "read-only plan", "serial": args.serial, "twrp": device["twrp"],
                      "checked_layout": "M19_X6 reference GPT; this does not identify the physical board",
                      "rom_images_verified": list(images), "sd_images_verified": list(sd_paths),
                      "own_backups_verified": bool(backups), "mounted_originals": mounted_originals(device["mounts"]),
                      "would_write_only": ["boot", "system", "para command first 32 bytes"],
                      "device_mutated": False}
        print(json.dumps(result, indent=2))
        if args.flash or args.normal_boot:
            print("Leave SD inserted. Ready for your explicit normal reboot: adb -s SERIAL reboot")
        return 0
    except (InstallError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
