#!/system/bin/sh
test "$BOOTMODE" = true || abort 'Install from Magisk app in the running Android 10 port.'
test "$(getprop ro.hardware)" = mt6580 || abort 'This module is scoped to the M19_X6/MT6580 port.'
test -x /sbin/magisk || abort 'The checked /sbin Magisk layout is required.'
test -f /system/xbin/su || abort 'Expected PHH su entry is missing.'
set_perm "$MODPATH/module.prop" 0 0 0644
set_perm "$MODPATH/post-fs-data.sh" 0 0 0755
set_perm "$MODPATH/service.sh" 0 0 0755
mkdir -p "$MODPATH/system/xbin"
# The Magisk app expects PATH directories containing su to also have magisk.
# Use the actual running inode: Magisk authenticates client executables.
ln -s /sbin/magisk "$MODPATH/system/xbin/magisk"
ui_print 'Disable/remove this module and reboot to restore PHH.'
ui_print 'No apps or application data are deleted.'
