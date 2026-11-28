#!/system/bin/sh
# Late stage runs after PHH's own early mounts and class main start requests.
# Bind Magisk itself to the checked su entry; no source file is removed.
set -eu
MODDIR=${0%/*}
exec >> "$MODDIR/action.log" 2>&1
test "$(getprop ro.hardware)" = mt6580
test -x /sbin/magisk
test -f /system/xbin/su
setprop ctl.stop sudaemon
mount -o bind /sbin/magisk /system/xbin/su
test "$(sha256sum /sbin/magisk | cut -d ' ' -f 1)" = "$(sha256sum /system/xbin/su | cut -d ' ' -f 1)"
echo 'PHH disabled; standard xbin su now uses Magisk'
