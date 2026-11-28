#!/usr/bin/env python3
"""Register the already mounted p3 in Apps2SD 16 without startup hooks.

Default mode only inspects the device and saves a private plan. --configure
stops Apps2SD, backs up its DB/preferences, inserts one filesystem row only
when empty, and changes two preferences. It does not mount, link applications,
format partitions, install/uninstall APKs, or reboot the device.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import uuid
import xml.etree.ElementTree as ET

PACKAGE = "in.co.pricealert.apps2sd"
# aes extends SQLiteOpenHelper(context, "apps2sd.db", ...). The exported
# /data/apps2sd/apps2sdpro.db is a native-tool snapshot, not the state owner.
DATABASE = f"/data/data/{PACKAGE}/databases/apps2sd.db"
PREFERENCES = f"/data/data/{PACKAGE}/shared_prefs/{PACKAGE}_preferences.xml"
EXPECTED_ROW = ("mmcblk1", "/dev/block/mmcblk1p3", "/dev/block/mmcblk1p3", "ext4", "", "")
COLUMNS = ("_id", "name", "path_1", "path_2", "type", "pre_script", "post_script")
PREFERENCE_CHANGES = {"disable_auto_mount": "true", "auto_soft_reboot": "false"}


class ConfigurationError(Exception):
    pass


class Adb:
    def __init__(self, executable: str, serial: str):
        self.prefix = [executable, "-s", serial]

    def run(self, *arguments: str) -> bytes:
        result = subprocess.run([*self.prefix, *arguments], capture_output=True)
        if result.returncode:
            raise ConfigurationError(result.stderr.decode("utf-8", "replace")
                                     + result.stdout.decode("utf-8", "replace"))
        return result.stdout

    def shell(self, command: str) -> str:
        return self.run("shell", command).decode("utf-8", "replace").replace("\r", "").strip()

    def read(self, path: str) -> bytes:
        return self.run("exec-out", f"cat {shlex.quote(path)} 2>/dev/null")


def sql_query(adb: Adb, sql: str) -> str:
    # This device's SQLite shell lacks -readonly, but honors mode=ro URIs.
    uri = "file:" + DATABASE + "?mode=ro"
    return adb.shell("/system/bin/sqlite3 -bail " + shlex.quote(uri) + " " + shlex.quote(sql))


def preference_map(raw: bytes) -> dict[str, tuple[str, dict, str]]:
    root = ET.fromstring(raw)
    if root.tag != "map":
        raise ConfigurationError("SharedPreferences XML has an unexpected root")
    found = {}
    for item in root:
        name = item.attrib.get("name")
        if not name or name in found:
            raise ConfigurationError("Preference names are missing or duplicated")
        found[name] = (item.tag, dict(item.attrib), ET.tostring(item, encoding="unicode"))
    return found


def update_preferences(raw: bytes) -> bytes:
    root = ET.fromstring(raw)
    before = preference_map(raw)
    for name, value in PREFERENCE_CHANGES.items():
        entries = [item for item in root if item.attrib.get("name") == name]
        if entries:
            item = entries[0]
            if item.tag != "boolean":
                raise ConfigurationError(f"Preference {name} has an unexpected type")
        else:
            item = ET.SubElement(root, "boolean", {"name": name})
        item.set("value", value)
    result = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    after = preference_map(result)
    for name, content in before.items():
        if name not in PREFERENCE_CHANGES and after.get(name) != content:
            raise ConfigurationError(f"Unrelated preference would change: {name}")
    if set(after) - set(before) - set(PREFERENCE_CHANGES):
        raise ConfigurationError("Unexpected preference keys were added")
    return result


def validate_rows(rows: list[tuple]) -> bool:
    if not rows:
        return True
    if rows == [EXPECTED_ROW]:
        return False
    raise ConfigurationError("Existing filesystem metadata differs; it will not be overwritten")


def check_device(adb: Adb) -> dict:
    if adb.shell("id -u") != "0":
        raise ConfigurationError("An existing root ADB connection is required; this tool will not enable it")
    if adb.shell("getprop ro.build.version.sdk") != "29":
        raise ConfigurationError("Android 10 is required")
    package_dump = adb.shell(f"dumpsys package {PACKAGE}")
    match = re.search(r"\bversionCode=(\d+)\b", package_dump)
    if not match or match.group(1) != "160":
        raise ConfigurationError("Only the audited Apps2SD versionCode 160 is supported")
    if adb.shell("getprop sys.apps2sd.mount_state") != "ready":
        raise ConfigurationError("The identity-checked p3 mount owner has not reported ready")
    mounts = adb.shell("cat /proc/1/mounts").splitlines()
    selected = [line.split() for line in mounts if len(line.split()) >= 4
                and line.split()[1] == "/data/sdext2"]
    if len(selected) != 1 or selected[0][0] != "/dev/block/mmcblk1p3" \
            or selected[0][2] != "ext4" or "rw" not in selected[0][3].split(","):
        raise ConfigurationError("PID1 does not have the expected rw p3 ext4 mount at /data/sdext2")
    if adb.shell("cat /sys/block/mmcblk1/mmcblk1p3/ro") != "0":
        raise ConfigurationError("p3 remains block read-only")
    if sql_query(adb, "PRAGMA integrity_check;") != "ok":
        raise ConfigurationError("Apps2SD database integrity check failed")
    info = [line.split("|") for line in sql_query(adb, "PRAGMA table_info(filesystem);").splitlines()]
    if tuple(line[1] for line in info) != COLUMNS or tuple(line[2].lower() for line in info) != (
            "integer", "text", "text", "text", "text", "text", "text"):
        raise ConfigurationError("The filesystem table schema differs from the audited Apps2SD version")
    if info[4][3] != "1" or info[0][5] != "1":
        raise ConfigurationError("The audited required type/primary key constraints are missing")
    create = sql_query(adb, "SELECT sql FROM sqlite_master WHERE type='table' AND name='filesystem';")
    if not re.search(r"\btype\s+text\s+unique\s+not\s+null\b", create, re.I):
        raise ConfigurationError("The filesystem type uniqueness constraint differs")
    fields = ",".join("hex(" + name + ")" for name in COLUMNS[1:])
    text = sql_query(adb, "SELECT " + fields + " FROM filesystem ORDER BY _id;")
    rows = [tuple(bytes.fromhex(value).decode("utf-8") for value in line.split("|"))
            for line in text.splitlines()]
    insert = validate_rows(rows)
    preferences = adb.read(PREFERENCES)
    checked = preference_map(preferences)
    app_version = checked.get("app_version")
    if app_version and (app_version[0] != "int" or app_version[1].get("value") != "160"):
        raise ConfigurationError("Apps2SD's stored app version differs")
    adb.shell(f"test ! -e {shlex.quote(PREFERENCES + '.bak')}")
    return {"app_version_code": 160, "filesystem_rows": rows, "insert_row": insert,
            "preferences": preferences, "updated_preferences": update_preferences(preferences)}


def validate_backup(path: Path, expected_rows: list[tuple]):
    connection = sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ConfigurationError("Private SQLite backup failed integrity check")
        rows = connection.execute("SELECT name,path_1,path_2,type,pre_script,post_script "
                                  "FROM filesystem ORDER BY _id").fetchall()
        if rows != [tuple(row) for row in expected_rows]:
            raise ConfigurationError("SQLite backup metadata differs from the stopped application")
    finally:
        connection.close()


def configure(adb: Adb, directory: Path, initial: dict):
    # Stop only the application being configured, never clear or uninstall it.
    adb.run("shell", "am", "force-stop", PACKAGE)
    state = check_device(adb)
    if state["filesystem_rows"] != initial["filesystem_rows"]:
        raise ConfigurationError("Filesystem metadata changed while preparing configuration")
    stage = "/data/local/tmp/apps2sd-external-config-" + uuid.uuid4().hex
    adb.shell("mkdir " + shlex.quote(stage))
    backup_remote = stage + "/apps2sd-before.db"
    source_uri = "file:" + DATABASE + "?mode=ro"
    backup_command = ".backup " + backup_remote
    adb.shell("/system/bin/sqlite3 -bail " + shlex.quote(source_uri) + " " + shlex.quote(backup_command))
    backup_local = directory / "apps2sd-before.db"
    adb.run("pull", backup_remote, str(backup_local))
    validate_backup(backup_local, state["filesystem_rows"])
    prefs_before = directory / "preferences-before.xml"
    prefs_before.write_bytes(state["preferences"])
    prefs_after = directory / "preferences-after.xml"
    prefs_after.write_bytes(state["updated_preferences"])
    if state["insert_row"]:
        values = ",".join("'" + value + "'" for value in EXPECTED_ROW)
        sql = ("BEGIN IMMEDIATE; INSERT INTO filesystem(name,path_1,path_2,type,pre_script,post_script) "
               "SELECT " + values + " WHERE NOT EXISTS(SELECT 1 FROM filesystem); COMMIT; PRAGMA integrity_check;")
        result = adb.shell("/system/bin/sqlite3 -bail " + shlex.quote(DATABASE) + " " + shlex.quote(sql))
        if result != "ok":
            raise ConfigurationError("Database insert did not pass integrity check; original backup is preserved")
    staged_preferences = stage + "/preferences-after.xml"
    adb.run("push", str(prefs_after), staged_preferences)
    temp_preferences = PREFERENCES + ".apps2sd-external-new"
    before_sha = hashlib.sha256(state["preferences"]).hexdigest()
    after_sha = hashlib.sha256(state["updated_preferences"]).hexdigest()
    command = (
        "set -e; test ! -e " + shlex.quote(temp_preferences) + "; "
        "test \"$(sha256sum " + shlex.quote(PREFERENCES) + " | cut -d ' ' -f 1)\" = " + before_sha + "; "
        "cp " + shlex.quote(staged_preferences) + " " + shlex.quote(temp_preferences) + "; "
        "/sbin/magisk --clone-attr " + shlex.quote(PREFERENCES) + " " + shlex.quote(temp_preferences) + "; "
        "test \"$(sha256sum " + shlex.quote(temp_preferences) + " | cut -d ' ' -f 1)\" = " + after_sha + "; "
        "mv " + shlex.quote(temp_preferences) + " " + shlex.quote(PREFERENCES) + "; sync"
    )
    adb.shell(command)
    verified = check_device(adb)
    if verified["insert_row"] or verified["preferences"] != state["updated_preferences"]:
        raise ConfigurationError("Post-configuration metadata/preferences verification failed")
    result = {"configured": True, "database_row_added": state["insert_row"],
              "changed_preferences": PREFERENCE_CHANGES, "startup_hooks_created": False,
              "private_remote_backup": backup_remote, "database_backup_sha256": hashlib.sha256(backup_local.read_bytes()).hexdigest(),
              "preferences_before_sha256": before_sha, "preferences_after_sha256": after_sha}
    (directory / "configured.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--result-dir", required=True, type=Path)
    parser.add_argument("--configure", action="store_true")
    args = parser.parse_args()
    if args.result_dir.exists() or args.result_dir.is_symlink():
        raise FileExistsError("Use a new private result directory")
    adb = Adb(args.adb, args.serial)
    state = check_device(adb)
    args.result_dir.mkdir(parents=True, exist_ok=False)
    plan = {"configured": False, "app_version_code": 160,
            "filesystem_row_would_be_added": state["insert_row"],
            "changed_preferences": PREFERENCE_CHANGES, "startup_hooks_would_be_created": False,
            "requires_existing_identity_checked_mount": True}
    (args.result_dir / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    result = configure(adb, args.result_dir, state) if args.configure else plan
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
