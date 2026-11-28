#!/usr/bin/env python3
"""Build the checked VORMOR Android 10 port on the host; never access a device.

Python 3.10+, magiskboot, and Linux e2fsprogs are required. Windows uses WSL
for e2fsprogs. Inputs remain read-only and each build owns a new output folder.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import zlib

CONFIGS = Path(__file__).resolve().parent.parent / "configs"
SPARSE_MAGIC = 0xED26FF3A
BUFFER_BYTES = 1024 * 1024


class BuildError(Exception):
    """A checked input, tool, or output boundary failed; leave evidence in place."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(BUFFER_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def check_hash(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise BuildError(f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}")


def config_file(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise BuildError(f"Config path leaves its directory: {relative}")
    return path


def validate_member_name(name: str) -> None:
    path = PurePosixPath(name)
    # Archive names use POSIX separators, but staging also runs on Windows.
    # A backslash or drive prefix must not become a native path escape there.
    if (not name or name == "." or path.is_absolute() or ".." in path.parts
            or path.as_posix() != name or "\\" in name or ":" in name
            or any(c.isspace() or c == "\0" for c in name)):
        raise BuildError(f"Unsafe overlay member path: {name!r}")


def reserve_output(path: Path) -> Path:
    # is_symlink catches dangling links as well as existing links.
    if path.exists() or path.is_symlink():
        raise BuildError(f"Output must be a new directory: {path}")
    path.mkdir(parents=True, exist_ok=False)
    (path / ".build-owner.json").write_text(
        '{"owner":"vormor-host-port-builder","format_version":1}\n', encoding="utf-8"
    )
    return path.resolve()


def check_disk_space(output: Path, required: int) -> None:
    ancestor = output.parent
    while not ancestor.exists():
        if ancestor.parent == ancestor:
            raise BuildError("The output filesystem does not exist")
        ancestor = ancestor.parent
    available = shutil.disk_usage(ancestor).free
    if available < required:
        raise BuildError(f"Output needs at least {required} free bytes; only {available} are available")


def read_exact(stream, count: int) -> bytes:
    data = stream.read(count)
    if len(data) != count:
        raise BuildError(f"Truncated image: needed {count} bytes, received {len(data)}")
    return data


def convert_sparse(source, output, max_bytes: int) -> int:
    """Convert Android sparse RAW/FILL/DONT_CARE/CRC32 chunks, checking dimensions."""
    header = read_exact(source, 28)
    magic, major, minor, file_header, chunk_header, block_size, blocks, chunks, checksum = (
        struct.unpack("<I4H4I", header)
    )
    if magic != SPARSE_MAGIC or major != 1:
        raise BuildError("Unsupported Android sparse image version")
    if file_header < 28 or chunk_header < 12 or not block_size or block_size % 4:
        raise BuildError("Invalid Android sparse header dimensions")
    declared_bytes = blocks * block_size
    if declared_bytes > max_bytes:
        raise BuildError("Sparse output exceeds the checked partition capacity")
    read_exact(source, file_header - 28)
    written = 0
    crc = 0

    def write_data(data: bytes) -> None:
        nonlocal written, crc
        output.write(data)
        written += len(data)
        crc = zlib.crc32(data, crc)

    for _ in range(chunks):
        kind, reserved, chunk_blocks, total_size = struct.unpack("<2H2I", read_exact(source, 12))
        read_exact(source, chunk_header - 12)
        count = chunk_blocks * block_size
        if written + count > declared_bytes:
            raise BuildError("Sparse chunks exceed the declared output length")
        payload = total_size - chunk_header
        if kind == 0xCAC1:
            if payload != count:
                raise BuildError("RAW sparse chunk length mismatch")
            remaining = count
            while remaining:
                data = read_exact(source, min(remaining, BUFFER_BYTES))
                write_data(data)
                remaining -= len(data)
        elif kind in (0xCAC2, 0xCAC3):
            if payload != (4 if kind == 0xCAC2 else 0):
                raise BuildError("FILL/DONT_CARE sparse chunk length mismatch")
            pattern = read_exact(source, 4) if kind == 0xCAC2 else b"\0" * 4
            data = pattern * (BUFFER_BYTES // 4)
            remaining = count
            while remaining:
                part = data[:min(remaining, BUFFER_BYTES)]
                write_data(part)
                remaining -= len(part)
        elif kind == 0xCAC4:
            if chunk_blocks != 0 or payload != 4:
                raise BuildError("Invalid CRC32 sparse chunk")
            if struct.unpack("<I", read_exact(source, 4))[0] != crc:
                raise BuildError("Sparse CRC32 chunk mismatch")
        else:
            raise BuildError(f"Unsupported sparse chunk type: {kind:#x}")
    if written != declared_bytes:
        raise BuildError("Sparse chunks do not fill the declared image length")
    if checksum and crc != checksum:
        raise BuildError("Sparse image header CRC32 mismatch")
    if source.read(1):
        raise BuildError("Unexpected bytes after the final sparse chunk")
    return written


def cpio_members(data: bytes) -> dict:
    members = {}
    offset = 0
    while offset + 110 <= len(data):
        header = data[offset:offset + 110]
        if header[:6] not in (b"070701", b"070702"):
            raise BuildError("Invalid CPIO newc header")
        try:
            fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        except ValueError as error:
            raise BuildError("Invalid CPIO hexadecimal field") from error
        mode, uid, gid, size, namesize = fields[1], fields[2], fields[3], fields[6], fields[11]
        start = offset + 110
        name_end = start + namesize
        content_start = (name_end + 3) & ~3
        content_end = content_start + size
        if namesize < 1 or name_end > len(data) or content_end > len(data):
            raise BuildError("Truncated CPIO member")
        if data[name_end - 1] != 0:
            raise BuildError("CPIO member name has no terminator")
        name = data[start:name_end - 1].decode("utf-8")
        content = data[content_start:content_end]
        offset = (content_end + 3) & ~3
        if name == "TRAILER!!!":
            return members
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or name in members:
            raise BuildError(f"Unsafe or duplicate CPIO member name: {name}")
        members[name] = (mode, uid, gid, content)
    raise BuildError("CPIO trailer is missing")


def load_configs(root: Path):
    profile = json.loads((root / "profile.json").read_text(encoding="utf-8"))
    overlay = json.loads((root / "overlay.json").read_text(encoding="utf-8"))
    system = json.loads((root / "system.json").read_text(encoding="utf-8"))
    names = set()
    for entry in overlay["entries"]:
        name = entry["path"]
        validate_member_name(name)
        if name in names:
            raise BuildError(f"Duplicate overlay member path: {name}")
        names.add(name)
        kind = entry["mode"] & 0o170000
        if kind not in (0o040000, 0o100000) or (entry["source"] is None) != (kind == 0o040000):
            raise BuildError(f"Overlay member type does not match its payload: {name}")
    for name in overlay["removed"]:
        validate_member_name(name)
    for entry in overlay["entries"] + system["compatibility_libraries"]:
        if entry["source"] is not None:
            check_hash(config_file(root, entry["source"]), entry["sha256"])
    return profile, overlay, system


def run_tool(command: list[str], cwd: Path, log: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, capture_output=True)
    with log.open("ab") as stream:
        stream.write(result.stdout + result.stderr)
    if result.returncode:
        diagnostic = (result.stdout + result.stderr).decode(errors="replace")[-2000:]
        raise BuildError(f"Tool failed ({result.returncode}): {command[0]}\n{diagnostic}")
    return result


def build_boot(args) -> Path:
    profile, overlay, _ = load_configs(args.configs)
    base = args.base_boot.resolve()
    check_hash(base, profile["base_boot_sha256"])
    if args.vendor_cil is not None:
        check_hash(args.vendor_cil, profile["vendor_cil_sha256"])
    tool = args.magiskboot.resolve()
    if not tool.is_file():
        raise BuildError("The explicit magiskboot executable does not exist")
    if args.magiskboot_sha256:
        check_hash(tool, args.magiskboot_sha256)
    # This profile keeps two kernel/ramdisk unpacks, an overlay and a boot image.
    check_disk_space(args.output_dir, 4 * profile["boot_partition_bytes"])
    out = reserve_output(args.output_dir)
    work = out / "work"
    work.mkdir()
    log = out / "magiskboot.log"
    run_tool([str(tool), "unpack", str(base)], work, log)
    before = cpio_members((work / "ramdisk.cpio").read_bytes())
    check_hash(work / "kernel", profile["kernel_sha256"])
    check_hash(work / "kernel_dtb", profile["dtb_sha256"])
    commands = []
    payload_dir = work / "overlay"
    for entry in overlay["entries"]:
        name = entry["path"]
        mode = entry["mode"]
        if entry["operation"] == "change" and name not in before:
            raise BuildError(f"Expected base CPIO member is missing: {name}")
        if entry["operation"] == "add" and name in before:
            raise BuildError(f"New CPIO member already exists: {name}")
        if entry["source"] is None:
            commands.append(f"mkdir {mode & 0o7777:04o} {name}")
        else:
            target = payload_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(config_file(args.configs, entry["source"]), target)
            # CPIO's CLI splits words. A relative staging path avoids spaces in
            # user-supplied parent directories.
            commands.append(f"add {mode & 0o7777:04o} {name} overlay/{name}")
    commands.extend(f"rm {name}" for name in overlay["removed"])
    run_tool([str(tool), "cpio", "ramdisk.cpio", *commands], work, log)
    image = out / "boot-android10-port.img"
    run_tool([str(tool), "repack", str(base), str(image)], work, log)
    verify = out / "verified"
    verify.mkdir()
    run_tool([str(tool), "unpack", str(image)], verify, log)
    after = cpio_members((verify / "ramdisk.cpio").read_bytes())
    expected = dict(before)
    for name in overlay["removed"]:
        del expected[name]
    for entry in overlay["entries"]:
        payload = b"" if entry["source"] is None else config_file(args.configs, entry["source"]).read_bytes()
        expected[entry["path"]] = (entry["mode"], entry["uid"], entry["gid"], payload)
    if after != expected:
        raise BuildError("Repacked CPIO differs from the declared overlay or base ownership")
    check_hash(verify / "kernel", profile["kernel_sha256"])
    check_hash(verify / "kernel_dtb", profile["dtb_sha256"])
    if image.stat().st_size != profile["boot_partition_bytes"]:
        raise BuildError("Repacked boot does not match the checked boot partition length")
    check_hash(base, profile["base_boot_sha256"])
    manifest = {
        "artifact": image.name, "sha256": sha256_file(image), "bytes": image.stat().st_size,
        "base_boot_sha256": profile["base_boot_sha256"], "magiskboot_sha256": sha256_file(tool),
        "kernel_sha256": sha256_file(verify / "kernel"), "dtb_sha256": sha256_file(verify / "kernel_dtb"),
        "overlay_verified": True, "device_access": False,
        "validation": "Host repack and complete CPIO comparison; public helper has not been boot tested.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return image


class LinuxTools:
    def __init__(self, args, output: Path):
        self.distro = args.distro
        self.debugfs = args.debugfs
        self.e2fsck = args.e2fsck
        self.output = output

    def path(self, path: Path) -> str:
        path = path.resolve()
        if os.name != "nt":
            return str(path)
        if len(path.drive) != 2 or path.drive[1] != ":":
            raise BuildError("WSL builds require paths on a mounted local drive")
        return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]

    def run(self, program: str, arguments: list[str]):
        # The metadata checks consume e2fsprogs' English field labels.
        command = ["env", "LC_ALL=C", program, *arguments]
        if os.name == "nt":
            prefix = ["wsl.exe"]
            if self.distro:
                prefix.extend(["-d", self.distro])
            command = [*prefix, "--", *command]
        return run_tool(command, self.output, self.output / "e2fsprogs.log")

    def command(self, image: Path, command: str):
        return self.run(self.debugfs, ["-R", command, self.path(image)])

    def dump(self, image: Path, internal: str, target: Path) -> bytes:
        self.command(image, f"dump {debugfs_quote(internal)} {debugfs_quote(self.path(target))}")
        if not target.is_file():
            raise BuildError(f"debugfs did not dump {internal}; inspect its log")
        return target.read_bytes()


def debugfs_quote(value: str) -> str:
    if any(c in value for c in ("\0", "\n", "\r")):
        raise BuildError("A debugfs path contains an unsupported control character")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def classify_system(path: Path, profile: dict) -> str:
    with path.open("rb") as stream:
        prefix = stream.read(6)
    if prefix == b"\xfd7zXZ\x00":
        kind = "xz"
    elif prefix[:4] == struct.pack("<I", SPARSE_MAGIC):
        kind = "sparse"
    else:
        kind = "raw"
    check_hash(path, profile["phh_system"][kind + "_sha256"])
    return kind


class HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def stock_raw(source: Path, kind: str, target: Path, profile: dict) -> None:
    if kind == "xz":
        # Hash the decompressed sparse stream while converting it. Keeping an
        # additional 1.1 GB sparse working file is unnecessary.
        with lzma.open(source, "rb") as stream, target.open("xb") as output:
            reader = HashingReader(stream)
            convert_sparse(reader, output, profile["system_partition_bytes"])
        if reader.digest.hexdigest() != profile["phh_system"]["sparse_sha256"]:
            raise BuildError("Decompressed sparse source SHA-256 mismatch")
    elif kind == "sparse":
        with source.open("rb") as stream, target.open("xb") as output:
            convert_sparse(stream, output, profile["system_partition_bytes"])
    else:
        shutil.copyfile(source, target)
    if target.stat().st_size != profile["phh_system"]["raw_bytes"]:
        raise BuildError("Converted PHH raw image length mismatch")
    check_hash(target, profile["phh_system"]["raw_sha256"])


def build_system(args) -> Path:
    profile, _, config = load_configs(args.configs)
    source = args.phh_system.resolve()
    kind = classify_system(source, profile)
    if args.systemui_apk is not None:
        check_hash(args.systemui_apk, config["optional_systemui"]["patched_sha256"])
    verification_bytes = 2 * config["archive_cil"]["bytes"] + BUFFER_BYTES
    verification_bytes += sum(config_file(args.configs, entry["source"]).stat().st_size
                              for entry in config["compatibility_libraries"])
    if args.systemui_apk is not None:
        verification_bytes += config["optional_systemui"]["source_bytes"] + args.systemui_apk.stat().st_size
    check_disk_space(args.output_dir, profile["phh_system"]["raw_bytes"] + verification_bytes)
    out = reserve_output(args.output_dir)
    work = out / "work"
    work.mkdir()
    image = out / "system-android10-port.raw.img"
    stock_raw(source, kind, image, profile)
    tools = LinuxTools(args, out)
    replacements = {}
    for index, internal in enumerate(config["text_patches"]):
        old = tools.dump(image, internal, work / f"source-text-{index}.txt").decode("utf-8")
        if internal.endswith("init.legacy-gsi.rc"):
            new = "import /system/etc/init/gsi/init.vndk-27.rc\n"
        elif internal.endswith("apex-setup.rc"):
            new = "# Per-device APEX and isolated storage bootstrap is defined in /init.android10-trial.rc.\n"
        else:
            anchor = "ro.adb.secure=0"
            if old.count(anchor) != 1:
                raise BuildError("Expected exactly one stock ro.adb.secure default")
            new = old.replace(anchor, "ro.adb.secure=1", 1)
        payload = work / f"patch-text-{index}.txt"
        payload.write_text(new, encoding="utf-8", newline="\n")
        stat = tools.command(image, f"stat {debugfs_quote(internal)}").stdout.decode(errors="replace")
        mode = re.search(r"Mode:\s*([0-7]+)", stat)
        owner = re.search(r"User:\s*(\d+)\s+Group:\s*(\d+)", stat)
        if not mode or not owner:
            raise BuildError(f"Cannot read source inode ownership: {internal}")
        replacements[internal] = {
            "source": payload, "content": new.encode(), "mode": 0o100000 | int(mode.group(1), 8),
            "uid": int(owner.group(1)), "gid": int(owner.group(2)), "selinux": "u:object_r:system_file:s0",
        }
    for entry in config["compatibility_libraries"]:
        payload = config_file(args.configs, entry["source"])
        replacements[entry["path"]] = dict(entry, source=payload, content=payload.read_bytes())
    cil = config["archive_cil"]
    old_cil = tools.dump(image, cil["source"], work / "platform.cil")
    if hashlib.sha256(old_cil).hexdigest() != cil["sha256"]:
        raise BuildError("Stock platform CIL content mismatch")
    stat_before = tools.command(image, f"stat {debugfs_quote(cil['source'])}").stdout
    commands = []
    for index, (internal, entry) in enumerate(replacements.items()):
        if internal in config["text_patches"]:
            commands.append(f"rm {debugfs_quote(internal)}")
        context = work / f"context-{index}.bin"
        context.write_bytes(entry["selinux"].encode() + b"\0")
        commands.extend([
            f"write {debugfs_quote(tools.path(entry['source']))} {debugfs_quote(internal)}",
            f"set_inode_field {debugfs_quote(internal)} mode 0{entry['mode']:o}",
            f"set_inode_field {debugfs_quote(internal)} uid {entry['uid']}",
            f"set_inode_field {debugfs_quote(internal)} gid {entry['gid']}",
            f"ea_set -f {debugfs_quote(tools.path(context))} {debugfs_quote(internal)} security.selinux",
        ])
    commands.extend(f"rm {debugfs_quote(path)}" for path in config["removed"])
    commands.extend([
        f"ln {debugfs_quote(cil['source'])} {debugfs_quote(cil['target'])}",
        f"set_inode_field {debugfs_quote(cil['source'])} links_count 2",
        f"rm {debugfs_quote(cil['source'])}",
    ])
    command_file = work / "patch-system.debugfs"
    command_file.write_text("\n".join(commands) + "\n", encoding="utf-8")
    tools.run(tools.debugfs, ["-w", "-f", tools.path(command_file), tools.path(image)])
    verification = {}
    for index, (internal, entry) in enumerate(replacements.items()):
        content = tools.dump(image, internal, work / f"verified-{index}.bin")
        if content != entry["content"]:
            raise BuildError(f"Patched content mismatch: {internal}")
        stat = tools.command(image, f"stat {debugfs_quote(internal)}").stdout.decode(errors="replace")
        mode = re.search(r"Mode:\s*([0-7]+)", stat)
        owner = re.search(r"User:\s*(\d+)\s+Group:\s*(\d+)", stat)
        context = tools.command(image, f"ea_list {debugfs_quote(internal)}").stdout.decode(errors="replace")
        if (not mode or not owner or int(mode.group(1), 8) != entry["mode"] & 0o7777
                or int(owner.group(1)) != entry["uid"] or int(owner.group(2)) != entry["gid"]
                or entry["selinux"] not in context):
            raise BuildError(f"Patched ownership or SELinux context mismatch: {internal}")
        verification[internal] = hashlib.sha256(content).hexdigest()
    archived = tools.dump(image, cil["target"], work / "archived-platform.cil")
    if archived != old_cil or tools.command(image, f"stat {debugfs_quote(cil['target'])}").stdout != stat_before:
        raise BuildError("Archived platform CIL inode or content changed")
    for internal in [*config["removed"], cil["source"]]:
        result = tools.command(image, f"stat {debugfs_quote(internal)}")
        if result.stdout or b"File not found" not in result.stderr:
            raise BuildError(f"Removed image path still exists or could not be checked: {internal}")
    # Apply this separately signed compatibility APK only after the original
    # six port transforms have passed their content/inode checks.
    if args.systemui_apk is not None:
        entry = config["optional_systemui"]
        internal = entry["path"]
        original = tools.dump(image, internal, work / "source-systemui.apk")
        if hashlib.sha256(original).hexdigest() != entry["source_sha256"]:
            raise BuildError("SystemUI inside the source image differs from the pinned patch input")
        context_file = work / "systemui-context.bin"
        context_file.write_bytes(entry["selinux"].encode() + b"\0")
        patch_commands = [
            f"rm {debugfs_quote(internal)}",
            f"write {debugfs_quote(tools.path(args.systemui_apk))} {debugfs_quote(internal)}",
            f"set_inode_field {debugfs_quote(internal)} mode 0{entry['mode']:o}",
            f"set_inode_field {debugfs_quote(internal)} uid {entry['uid']}",
            f"set_inode_field {debugfs_quote(internal)} gid {entry['gid']}",
            f"ea_set -f {debugfs_quote(tools.path(context_file))} {debugfs_quote(internal)} security.selinux",
        ]
        patch_file = work / "patch-systemui.debugfs"
        patch_file.write_text("\n".join(patch_commands) + "\n", encoding="utf-8")
        tools.run(tools.debugfs, ["-w", "-f", tools.path(patch_file), tools.path(image)])
        patched = tools.dump(image, internal, work / "verified-systemui.apk")
        if hashlib.sha256(patched).hexdigest() != entry["patched_sha256"]:
            raise BuildError("SystemUI APK did not survive the filesystem replacement")
        stat = tools.command(image, f"stat {debugfs_quote(internal)}").stdout.decode(errors="replace")
        mode = re.search(r"Mode:\s*([0-7]+)", stat)
        owner = re.search(r"User:\s*(\d+)\s+Group:\s*(\d+)", stat)
        context = tools.command(image, f"ea_list {debugfs_quote(internal)}").stdout.decode(errors="replace")
        if (not mode or not owner or int(mode.group(1), 8) != 0o644
                or int(owner.group(1)) != 0 or int(owner.group(2)) != 0
                or entry["selinux"] not in context):
            raise BuildError("SystemUI replacement ownership or SELinux context mismatch")
        check_hash(args.systemui_apk, entry["patched_sha256"])
        verification[internal] = entry["patched_sha256"]
    tools.run(tools.e2fsck, ["-f", "-n", tools.path(image)])
    if image.stat().st_size > profile["system_partition_bytes"]:
        raise BuildError("Patched image exceeds the checked system partition")
    check_hash(source, profile["phh_system"][kind + "_sha256"])
    manifest = {
        "artifact": image.name, "bytes": image.stat().st_size, "sha256": sha256_file(image),
        "source_kind": kind, "source_sha256": sha256_file(source),
        "verified_files": verification, "archived_cil_preserves_inode": True,
        "read_only_fsck_passed": True, "device_access": False,
        "systemui_patch_applied": args.systemui_apk is not None,
        "byte_identity": "Filesystem inode timestamps can differ from the original trial image.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return image


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    for name in ("boot", "system"):
        command = sub.add_parser(name)
        command.add_argument("--configs", type=Path, default=CONFIGS)
        command.add_argument("--output-dir", type=Path, required=True)
        if name == "boot":
            command.add_argument("--base-boot", type=Path, required=True)
            command.add_argument("--magiskboot", type=Path, required=True)
            command.add_argument("--magiskboot-sha256")
            command.add_argument("--vendor-cil", type=Path, help="Optionally verify your vendor CIL against this profile")
        else:
            command.add_argument("--phh-system", type=Path, required=True, help="Checked v222 stock .img.xz, sparse .img, or raw .img")
            command.add_argument("--systemui-apk", type=Path, help="Optional pinned, signed Mali EGL wallpaper compatibility APK")
            command.add_argument("--distro", help="WSL distro; omit to use the configured default")
            command.add_argument("--debugfs", default="debugfs", help="Linux executable name or path")
            command.add_argument("--e2fsck", default="e2fsck", help="Linux executable name or path")
    return cli


def main() -> int:
    args = parser().parse_args()
    try:
        image = build_boot(args) if args.command == "boot" else build_system(args)
    except (BuildError, OSError, UnicodeError, json.JSONDecodeError, lzma.LZMAError) as error:
        print(f"Build stopped: {error}", file=sys.stderr)
        return 1
    print(f"Built: {image}\nSHA-256: {sha256_file(image)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
