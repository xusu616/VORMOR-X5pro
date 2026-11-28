#!/system/bin/sh
# Only the dedicated trial files below are writable Android /data and /cache.
set -eu
host=/mnt/vendor/a10-test
files=$host/.codex-android10-test
host_mounted=0
data_attempted=0
cache_attempted=0
data_mounted=0
cache_mounted=0
nvdata_seed=/mnt/a10-nvdata-seed
nvdata_copy=/data/local/tmp/android10-nvdata-trial
nvdata_owner=/data/local/tmp/android10-nvdata-trial.owner
nvdata_seed_mounted=0
nvdata_bind_mounted=0
compat_source=/android10-vendor-lib/libeffectsconfig.so
compat_target=/system/lib/vndk-27/libeffectsconfig.so
compat_bind_owned=0

log() {
    echo "android10-trial8: $1" > /dev/kmsg
}

mount_source() {
    while read -r source target options; do
        if [ "$target" = "$1" ]; then
            echo "$source"
            return 0
        fi
    done < /proc/mounts
    return 1
}

mount_root() {
    while read -r mount_id parent_id block_device root target remainder; do
        if [ "$target" = "$1" ]; then
            echo "$root"
            return 0
        fi
    done < /proc/self/mountinfo
    return 1
}

cleanup_owned_mount() {
    target=$1
    expected_source=$2
    expected_root=$3
    mounted=$4
    [ "$mounted" = 1 ] || return 0
    actual_source=$(mount_source "$target") || { log "cleanup could not identify $target mount"; return 1; }
    actual_root=$(mount_root "$target") || { log "cleanup could not identify $target filesystem root"; return 1; }
    if [ "$actual_source" != "$expected_source" ] || [ "$actual_root" != "$expected_root" ]; then
        log "cleanup refused for unrelated $target mount"
        return 1
    fi
    umount "$target" || { log "cleanup could not unmount $target"; return 1; }
}

cleanup_loop() {
    device=$1
    image=$2
    target=$3
    mounted=$4
    attempted=$5
    [ "$attempted" = 1 ] || return 0
    backing=/sys/block/${device##*/}/loop/backing_file
    if [ -e "$backing" ]; then
        actual=$(cat "$backing") || return 1
        if [ "$actual" != "$image" ]; then
            log "cleanup refused for unrelated $device backing file"
            return 1
        fi
    elif [ "$mounted" = 1 ]; then
        log "cleanup refused: mounted $target lost its expected loop backing"
        return 1
    else
        return 0
    fi
    if [ "$mounted" = 1 ]; then
        actual_source=$(mount_source "$target") || return 1
        if [ "$actual_source" != "$device" ]; then
            log "cleanup refused for unrelated $target mount"
            return 1
        fi
        umount "$target" || { log "cleanup could not unmount $target"; return 1; }
    fi
    # Successful mounts have autoclear set, so umount may already release it.
    if [ -e "$backing" ]; then
        actual=$(cat "$backing") || return 1
        [ "$actual" = "$image" ] || return 1
        /system/bin/losetup -d "$device" || { log "cleanup could not detach $device"; return 1; }
    fi
}

fail() {
    log "$1; returning to recovery"
    cleanup_ok=1
    cleanup_owned_mount "$compat_target" rootfs "$compat_source" "$compat_bind_owned" || cleanup_ok=0
    cleanup_owned_mount /vendor/nvdata /dev/block/loop7 /local/tmp/android10-nvdata-trial "$nvdata_bind_mounted" || cleanup_ok=0
    cleanup_owned_mount "$nvdata_seed" /dev/block/mmcblk0p16 / "$nvdata_seed_mounted" || cleanup_ok=0
    cleanup_loop /dev/block/loop6 "$files/cache-test.img" /cache "$cache_mounted" "$cache_attempted" || cleanup_ok=0
    cleanup_loop /dev/block/loop7 "$files/userdata-test.img" /data "$data_mounted" "$data_attempted" || cleanup_ok=0
    if [ "$host_mounted" = 1 ] && [ "$cleanup_ok" = 1 ]; then
        if actual_source=$(mount_source "$host"); then
            if [ "$actual_source" = /dev/block/mmcblk1p1 ]; then
                umount "$host" || log "cleanup could not unmount test SD host"
            else
                log "cleanup refused for unrelated test SD host mount"
            fi
        else
            log "cleanup could not identify test SD host mount"
        fi
    elif [ "$cleanup_ok" != 1 ]; then
        log "test-resource cleanup incomplete; preserving SD host mount"
    fi
    /system/bin/reboot recovery
    exit 1
}

device_serial=$(/system/bin/getprop ro.boot.serialno) || fail "cannot read device boot serial"
[ -n "$device_serial" ] || fail "device boot serial is missing"
expected_owner=$device_serial:mmcblk0p16:v1

log "storage helper started"
/system/bin/blockdev --setro /dev/block/platform/mtk-msdc.0/11120000.msdc0/by-name/userdata || fail "cannot protect original userdata"
/system/bin/blockdev --setro /dev/block/platform/mtk-msdc.0/11120000.msdc0/by-name/cache || fail "cannot protect original cache"
if [ -b /dev/block/mmcblk1p3 ]; then
    /system/bin/blockdev --setro /dev/block/mmcblk1p3 || fail "cannot protect original Apps2SD partition"
fi
/system/bin/blockdev --setro /dev/block/mmcblk0p2 || fail "cannot protect original NVRAM partition"
/system/bin/blockdev --setro /dev/block/mmcblk0p3 || fail "cannot protect original protect1 partition"
/system/bin/blockdev --setro /dev/block/mmcblk0p4 || fail "cannot protect original protect2 partition"
/system/bin/blockdev --setro /dev/block/mmcblk0p16 || fail "cannot protect original nvdata partition"
if mount_source /data >/dev/null || mount_source /cache >/dev/null; then
    fail "data or cache is already mounted before isolated preparation"
fi
if mount_source "$host" >/dev/null; then
    fail "test SD host mountpoint is already occupied"
fi
if mount_source "$nvdata_seed" >/dev/null || mount_source /vendor/nvdata >/dev/null; then
    fail "NVRAM seed or target mountpoint is already occupied"
fi
[ -f "$compat_source" ] || fail "vendor effects parser compatibility file missing"
[ -f "$compat_target" ] || fail "VNDK27 effects parser target file missing"
if mount_source "$compat_target" >/dev/null; then
    fail "VNDK27 effects parser target is already independently mounted"
fi
[ ! -e /sys/block/loop7/loop/backing_file ] || fail "test userdata loop already belongs to another attachment"
[ ! -e /sys/block/loop6/loop/backing_file ] || fail "test cache loop already belongs to another attachment"
mount -o bind /fstab.android10-trial /vendor/etc/fstab.mt6580 || fail "cannot isolate vold fstab"
mkdir -p "$host" || fail "cannot create test SD host mountpoint"
mount -t vfat -o rw,nosuid,nodev,noexec,uid=0,gid=0,fmask=0077,dmask=0077 /dev/block/mmcblk1p1 "$host" || fail "SD test-storage mount failed"
host_mounted=1
[ -f "$files/userdata-test.img" ] || fail "test userdata file missing"
[ -f "$files/cache-test.img" ] || fail "test cache file missing"
# LOOP_SET_FD may succeed before losetup reports a later failure.
data_attempted=1
/system/bin/losetup /dev/block/loop7 "$files/userdata-test.img" || fail "test userdata loop setup failed"
cache_attempted=1
/system/bin/losetup /dev/block/loop6 "$files/cache-test.img" || fail "test cache loop setup failed"
mount -t ext4 -o nosuid,nodev,noatime /dev/block/loop7 /data || fail "test userdata mount failed"
data_mounted=1
/system/bin/losetup -d /dev/block/loop7 || fail "cannot mark test userdata loop for release after unmount"
[ "$(cat /sys/block/loop7/loop/autoclear)" = 1 ] || fail "test userdata loop autoclear was not set"
mount -t ext4 -o nosuid,nodev,noatime /dev/block/loop6 /cache || fail "test cache mount failed"
cache_mounted=1
/system/bin/losetup -d /dev/block/loop6 || fail "cannot mark test cache loop for release after unmount"
[ "$(cat /sys/block/loop6/loop/autoclear)" = 1 ] || fail "test cache loop autoclear was not set"
mkdir -p /data/local/tmp/android10-trial2 || fail "cannot create test boot-log directory"
mkdir -p "$nvdata_seed" || fail "cannot create original nvdata seed mountpoint"
mount -t ext4 -o ro,noload /dev/block/mmcblk0p16 "$nvdata_seed" || fail "cannot mount original nvdata seed read-only"
nvdata_seed_mounted=1
if [ -e "$nvdata_copy" ] || [ -L "$nvdata_copy" ]; then
    [ -d "$nvdata_copy" ] && [ ! -L "$nvdata_copy" ] || fail "test nvdata copy is not an owned directory"
    [ -f "$nvdata_owner" ] && [ ! -L "$nvdata_owner" ] || fail "test nvdata owner marker missing or invalid"
    actual_owner=$(cat "$nvdata_owner") || fail "cannot read test nvdata owner marker"
    [ "$actual_owner" = "$expected_owner" ] || fail "test nvdata owner marker does not match this device"
else
    [ ! -e "$nvdata_owner" ] && [ ! -L "$nvdata_owner" ] || fail "test nvdata owner marker exists without its copy"
    cp -a --preserve=all "$nvdata_seed" "$nvdata_copy" || fail "cannot copy original nvdata into isolated test data"
    [ -d "$nvdata_copy/APCFG" ] && [ -d "$nvdata_copy/media" ] || fail "new test nvdata copy lacks required directories"
    # A failed copy remains unmarked and will never be silently overwritten.
    sync || fail "cannot persist the new test nvdata copy"
    printf '%s\n' "$expected_owner" > "$nvdata_owner" || fail "cannot write test nvdata owner marker"
    sync || fail "cannot persist test nvdata owner marker"
fi
[ -d "$nvdata_copy/APCFG" ] && [ -d "$nvdata_copy/media" ] || fail "owned test nvdata copy lacks required directories"
mount -o bind "$nvdata_copy" /vendor/nvdata || fail "cannot bind isolated nvdata work directory"
nvdata_bind_mounted=1
[ "$(mount_source /vendor/nvdata)" = /dev/block/loop7 ] || fail "isolated nvdata bind has an unexpected source"
[ "$(mount_root /vendor/nvdata)" = /local/tmp/android10-nvdata-trial ] || fail "isolated nvdata bind has an unexpected filesystem root"
umount "$nvdata_seed" || fail "cannot unmount original nvdata seed"
nvdata_seed_mounted=0
mount -o bind "$compat_source" "$compat_target" || fail "cannot bind the vendor-compatible VNDK27 effects parser"
compat_bind_owned=1
[ "$(mount_source "$compat_target")" = rootfs ] || fail "effects parser compatibility bind has an unexpected source"
[ "$(mount_root "$compat_target")" = "$compat_source" ] || fail "effects parser compatibility bind has an unexpected filesystem root"
log "test storage, owned nvdata clone and VNDK27 effects parser ready; releasing storage gate"
setprop sys.android10.test_storage_ready 1 || fail "cannot release isolated storage gate"
