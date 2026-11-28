#!/usr/bin/env python3
"""Generate an identity-checked Magisk mount module on the host only.

The future, newly formatted p3 UUID must be supplied explicitly. No device is
queried or changed by this generator, and no filesystem is created or repaired.
Apps2SD must not install another startup mount script for the same partition.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import uuid
import zipfile

MODULE_ID = "m19x6_apps2sd_mount"
REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "modules/m19x6-magisk-only/META-INF/com/google/android/update-binary"
INSTALLER_SHA = "bcf4b1d9913f3af17755569c853e0b5a75b8005f6a18eb3f86dadcc0e968c29d"

POST_FS_DATA = r'''#!/system/bin/sh
# Synchronous Magisk post-fs-data stage. This module is the only p3 mount owner.
set -eu
MODDIR=${0%/*}
. "$MODDIR/identity.conf"
PARTITION=/dev/block/mmcblk1p3
MOUNTPOINT=/data/sdext2
PARTSYS=/sys/block/mmcblk1/mmcblk1p3
writable_owned=0
mount_owned=0
echo "$(/system/bin/date) Starting identity-checked p3 mount" >> "$MODDIR/mount.log"

mount_source() {
    while read -r source target type options remainder; do
        if [ "$target" = "$1" ]; then
            printf '%s\n' "$source"
            return 0
        fi
    done < /proc/mounts
    return 1
}

mount_options() {
    while read -r source target type options remainder; do
        if [ "$target" = "$1" ]; then
            printf '%s\n' "$options"
            return 0
        fi
    done < /proc/mounts
    return 1
}

fail() {
    echo "BLOCKED: $1" >> "$MODDIR/mount.log"
    # Roll back only resources successfully acquired by this invocation.
    if [ "$mount_owned" = 1 ]; then
        if [ "$(mount_source "$MOUNTPOINT")" = "$PARTITION" ]; then
            if /system/bin/umount "$MOUNTPOINT"; then
                mount_owned=0
            else
                echo 'Rollback could not unmount owned p3; preserving its block state' >> "$MODDIR/mount.log"
            fi
        fi
    fi
    if [ "$writable_owned" = 1 ] && [ "$mount_owned" = 0 ]; then
        /system/bin/blockdev --setro "$PARTITION" || echo 'Could not restore p3 block read-only' >> "$MODDIR/mount.log"
    fi
    /system/bin/setprop sys.apps2sd.mount_state blocked
    exit 1
}

# All external identity and ownership checks run before any block-state change.
[ "$(/system/bin/getprop ro.hardware)" = mt6580 ] || fail 'Unexpected hardware'
[ "$(/system/bin/getprop ro.build.version.sdk)" = 29 ] || fail 'Android 10 is required'
[ "$(mount_source /data)" = /dev/block/loop7 ] || fail 'Expected isolated loop7 /data'
[ -b "$PARTITION" ] || fail 'SD p3 block device is missing'
[ "$(/system/bin/cat /sys/block/mmcblk1/device/cid)" = "$EXPECTED_CID" ] || fail 'SD CID mismatch'
[ "$(/system/bin/cat /sys/block/mmcblk1/size)" = "$EXPECTED_DISK_SECTORS" ] || fail 'SD capacity mismatch'
[ "$(/system/bin/cat "$PARTSYS/start")" = "$EXPECTED_START" ] || fail 'p3 start sector mismatch'
[ "$(/system/bin/cat "$PARTSYS/size")" = "$EXPECTED_SECTORS" ] || fail 'p3 length mismatch'
actual_uuid=$(/system/bin/blkid -c /dev/null -w /dev/null -s UUID -o value "$PARTITION") || fail 'Could not read p3 UUID'
[ "$actual_uuid" = "$EXPECTED_UUID" ] || fail 'p3 UUID mismatch'
actual_type=$(/system/bin/blkid -c /dev/null -w /dev/null -s TYPE -o value "$PARTITION") || fail 'Could not read p3 filesystem type'
[ "$actual_type" = ext4 ] || fail 'p3 is not ext4'
[ ! -L "$MOUNTPOINT" ] || fail 'Mountpoint is a symbolic link'
if mount_source "$MOUNTPOINT" >/dev/null; then
    fail 'Mountpoint already has another mount owner'
fi
while read -r source target remainder; do
    [ "$source" != "$PARTITION" ] || fail 'p3 is already mounted elsewhere'
done < /proc/mounts

# Known Apps2SD startup locations must not compete with this module. Global
# post-fs-data scripts already ran by this point; disable them before installing.
for directory in /data/adb/post-fs-data.d /data/adb/service.d /system/etc/init.d /system/su.d /su/su.d; do
    for filename in 00000000apps2sd.sh 00000000apps2sd-main.sh 13-apps2sd.sh; do
        [ ! -e "$directory/$filename" ] || fail 'Another Apps2SD startup mount script exists'
    done
done

if [ -e "$MOUNTPOINT" ]; then
    [ -d "$MOUNTPOINT" ] || fail 'Mountpoint is not a directory'
else
    /system/bin/mkdir "$MOUNTPOINT" || fail 'Cannot create mountpoint'
    /system/bin/chown 0:0 "$MOUNTPOINT" || fail 'Cannot own mountpoint'
    /system/bin/chmod 0711 "$MOUNTPOINT" || fail 'Cannot set mountpoint permissions'
    /system/bin/restorecon "$MOUNTPOINT" || fail 'Cannot label mountpoint'
fi
/system/bin/setprop sys.apps2sd.mount_state mounting
/system/bin/blockdev --setrw "$PARTITION" || fail 'Cannot make matched p3 writable'
writable_owned=1
[ "$(/system/bin/cat "$PARTSYS/ro")" = 0 ] || fail 'p3 stayed block read-only'
/system/bin/mount -t ext4 -o rw,nosuid,nodev,noatime "$PARTITION" "$MOUNTPOINT" || fail 'ext4 p3 mount failed'
mount_owned=1
[ "$(mount_source "$MOUNTPOINT")" = "$PARTITION" ] || fail 'Mounted source differs from matched p3'
options=$(mount_options "$MOUNTPOINT") || fail 'Cannot inspect mounted p3 options'
case ",$options," in
    *,rw,*) ;;
    *) fail 'p3 mount is not writable' ;;
esac
# A new ext4 filesystem exposes its own previously unlabeled root inode here.
# Label only that mounted root; Apps2SD owns labels of any later linked data.
/system/bin/restorecon "$MOUNTPOINT" || fail 'Cannot label the mounted p3 root'
/system/bin/setprop sys.apps2sd.mount_state ready
echo 'READY: matching p3 is mounted rw at /data/sdext2' >> "$MODDIR/mount.log"
'''

CUSTOMIZE = r'''#!/system/bin/sh
[ "$BOOTMODE" = true ] || abort 'Install from Magisk in the running Android 10 port.'
[ "$(getprop ro.hardware)" = mt6580 ] || abort 'M19_X6/MT6580 is required.'
[ "$(getprop ro.build.version.sdk)" = 29 ] || abort 'Android 10 is required.'
set_perm "$MODPATH/module.prop" 0 0 0644
set_perm "$MODPATH/identity.conf" 0 0 0644
set_perm "$MODPATH/skip_mount" 0 0 0644
set_perm "$MODPATH/post-fs-data.sh" 0 0 0755
ui_print 'This module mounts only the exact configured SD p3.'
ui_print 'Disable Apps2SD startup mount scripts before enabling it.'
ui_print 'It does not format, fsck, migrate, or link application data.'
'''


def validate_identity(cid: str, start: int, sectors: int, disk: int,
                      filesystem_uuid: str) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F]{32}", cid):
        raise ValueError("SD CID must be 32 hexadecimal characters")
    if start <= 0 or sectors <= 0 or disk <= 0 or start + sectors > disk:
        raise ValueError("p3 geometry must be positive and lie inside the SD capacity")
    parsed = uuid.UUID(filesystem_uuid)
    if parsed.int == 0:
        raise ValueError("A nonzero, explicit UUID from the newly formatted p3 is required")
    return {"cid": cid.lower(), "start_sector": start, "sectors": sectors,
            "disk_sectors": disk, "uuid": str(parsed), "partition": "mmcblk1p3",
            "mountpoint": "/data/sdext2", "filesystem": "ext4"}


def generate(directory: Path, identity: dict, installer: Path = INSTALLER) -> Path:
    if directory.exists() or directory.is_symlink():
        raise FileExistsError("Use a new output directory; existing artifacts are not overwritten")
    if installer.is_symlink() or not installer.is_file():
        raise ValueError("Pinned Magisk module installer is missing")
    installer_bytes = installer.read_bytes()
    if hashlib.sha256(installer_bytes).hexdigest() != INSTALLER_SHA:
        raise ValueError("Magisk v30.6 module installer differs from the pinned input")
    # Keep the shell configuration inject-free even when called as a library.
    checked = validate_identity(identity["cid"], identity["start_sector"],
                                identity["sectors"], identity["disk_sectors"],
                                identity["uuid"])
    conf = (f"EXPECTED_CID={checked['cid']}\n"
            f"EXPECTED_START={checked['start_sector']}\n"
            f"EXPECTED_SECTORS={checked['sectors']}\n"
            f"EXPECTED_DISK_SECTORS={checked['disk_sectors']}\n"
            f"EXPECTED_UUID={checked['uuid']}\n")
    files = {
        "module.prop": (f"id={MODULE_ID}\nname=M19_X6 identity-checked Apps2SD mount\n"
                        "version=1.0\nversionCode=1\nauthor=xusu616\n"
                        "description=Mount only the configured SD p3 before package startup. No formatting or application-data changes.\n"),
        "identity.conf": conf,
        "post-fs-data.sh": POST_FS_DATA,
        "customize.sh": CUSTOMIZE,
        "skip_mount": "",
        "META-INF/com/google/android/updater-script": "#MAGISK\n",
    }
    directory.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    (directory / "META-INF/com/google/android/update-binary").write_bytes(installer_bytes)
    readme = (
        "This generated module contains this SD identity and should remain private.\n"
        "Supply only the UUID read after the explicitly authorized p3 format.\n"
        "Install from Magisk, after disabling Apps2SD's own startup mount method.\n"
        "Synchronous module post-fs-data runs after global post-fs-data.d scripts.\n"
        "A mismatch returns immediately and leaves p3 block read-only.\n"
        "A mount failure restores p3 read-only if this module can safely release it.\n"
        "No application linking, migration, fsck, formatting, or reboot is performed.\n"
        "If linked applications depend on p3, init must gate package startup on\n"
        "sys.apps2sd.mount_state=ready; a module alone cannot override Magisk's\n"
        "post-fs-data timeout. Do not enable competing legacy startup scripts.\n"
        "Disable/remove this module and reboot to stop its mount on the next boot.\n"
    )
    (directory / "USAGE.txt").write_text(readme, encoding="utf-8", newline="\n")
    (directory / "identity.json").write_text(json.dumps(checked, indent=2) + "\n", encoding="utf-8")
    archive = directory / "M19X6-Apps2SD-identity-mount-v1.0.zip"
    names = sorted([*files, "META-INF/com/google/android/update-binary"])
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for name in names:
            info = zipfile.ZipInfo(name, (2026, 11, 28, 0, 0, 0))
            info.create_system = 3
            mode = 0o755 if name.endswith(".sh") or name.endswith("update-binary") else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (directory / name).read_bytes())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None or z.namelist() != names:
            raise ValueError("Module ZIP verification failed")
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sd-cid", required=True)
    parser.add_argument("--p3-start-sector", required=True, type=int)
    parser.add_argument("--p3-sectors", required=True, type=int)
    parser.add_argument("--sd-sectors", required=True, type=int)
    parser.add_argument("--filesystem-uuid", required=True,
                        help="Actual new UUID after the authorized p3 format")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    identity = validate_identity(args.sd_cid, args.p3_start_sector, args.p3_sectors,
                                 args.sd_sectors, args.filesystem_uuid)
    archive = generate(args.output_dir, identity)
    print(json.dumps({"archive": str(archive),
                      "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                      "device_access": False, "contains_specific_sd_identity": True}, indent=2))


if __name__ == "__main__":
    main()
