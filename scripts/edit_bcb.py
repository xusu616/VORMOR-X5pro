#!/usr/bin/env python3
"""Edit only command[32] of an already captured para BCB sector on the host.

Use the original mtkclient ro/wo/ro CLI to transfer and verify the sector. This
helper does not open a USB port, initialize DA, flash a device, or reboot it.
"""
import argparse
import hashlib
from pathlib import Path
import sys

from flash_android10 import InstallError, normal_bcb


def edit(raw: bytes, recovery: bool) -> bytes:
    normalized = normal_bcb(raw)
    if recovery:
        return b"boot-recovery".ljust(32, b"\0") + normalized[32:]
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--recovery", action="store_true", help="Request recovery on the next boot")
    mode.add_argument("--normal", action="store_true", help="Clear the recovery/bootloader command")
    args = parser.parse_args()
    try:
        before = args.input.read_bytes()
        after = edit(before, args.recovery)
        with args.output.open("xb") as stream:
            stream.write(after)
        print("Prepared 512-byte BCB; bytes[32:512] are unchanged.")
        print("SHA-256: " + hashlib.sha256(after).hexdigest())
        return 0
    except (InstallError, OSError) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
