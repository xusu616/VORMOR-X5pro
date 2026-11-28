#!/system/bin/sh
# PHH Q su.rc starts sudaemon in class main. Disable it before zygote/main.
set -eu
MODDIR=${0%/*}
exec >> "$MODDIR/action.log" 2>&1
echo 'Disabling PHH sudaemon for this boot'
test -x /sbin/magisk
test "$(getprop ro.hardware)" = mt6580
setprop ctl.stop sudaemon
