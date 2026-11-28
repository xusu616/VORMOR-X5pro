#!/system/bin/sh
# Flush the diagnostic log while the reader runs; no storage or boot fallback.
PATH=/system/bin
export PATH
if [ "$#" -ge 1 ]; then
    log_file=$1
else
    boot_id=$(/system/bin/cat /proc/sys/kernel/random/boot_id) || exit 1
    [ -n "$boot_id" ] || exit 1
    log_file=/data/local/tmp/android10-trial2/kernel-live-trial8-$boot_id.txt
fi
reader_seconds=${2:-180}
/system/bin/printf 'LOGGER_START\n' > "$log_file" || exit 1
/system/bin/id >> "$log_file" 2>&1
/system/bin/cat /proc/self/attr/current >> "$log_file" 2>&1
/system/bin/grep -E '^(Uid|Gid|CapEff|CapBnd):' /proc/self/status >> "$log_file" 2>&1
/system/bin/printf 'BOOT_COMPLETED=' >> "$log_file"
/system/bin/getprop sys.boot_completed >> "$log_file" 2>&1
/system/bin/sync || exit 1
/system/bin/timeout --foreground "$reader_seconds" /system/bin/dmesg -w >> "$log_file" 2>&1 &
reader_pid=$!
checkpoint=0
# A fixed diagnostic window bounds a vanished or unreaped reader as well.
while [ "$checkpoint" -lt 720 ] && kill -0 "$reader_pid" 2>/dev/null; do
    /system/bin/sync || exit 1
    /system/bin/sleep 0.25
    checkpoint=$((checkpoint + 1))
done
wait "$reader_pid"
reader_status=$?
/system/bin/printf '\nLOGGER_EXIT=%s\n' "$reader_status" >> "$log_file"
/system/bin/sync
