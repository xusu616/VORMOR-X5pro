#!/usr/bin/env python3
"""Build the separate Kotlin Apps2SD probe with explicit host tools only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def run(command):
    result = subprocess.run([str(value) for value in command], check=False)
    if result.returncode:
        raise RuntimeError(f"Tool failed: {command[0]} ({result.returncode})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("java", "kotlin-compiler-cp", "kotlin-stdlib", "android-jar",
                 "aapt2", "d8", "zipalign", "apksigner", "key", "cert", "output-dir"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    if output.exists() or output.is_symlink():
        raise FileExistsError("Use a new output directory")
    source = ROOT / "apps/apps2sd-link-probe"
    sources = sorted((source / "src").glob("*.kt"))
    if not sources or not (source / "AndroidManifest.xml").is_file():
        raise ValueError("Probe sources are missing")
    output.mkdir(parents=True, exist_ok=False)
    jar = output / "apps2sd-probe.jar"
    separator = ";" if os.name == "nt" else ":"
    run([args.java, "-cp", args.kotlin_compiler_cp,
         "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", "-no-stdlib", "-no-reflect",
         "-jvm-target", "1.8", "-classpath", args.android_jar + separator + args.kotlin_stdlib,
         "-d", jar, *sources])
    dex = output / "dex"
    dex.mkdir()
    run([args.d8, "--min-api", "29", "--lib", args.android_jar, "--output", dex,
         jar, args.kotlin_stdlib])
    unsigned = output / "unsigned.apk"
    run([args.aapt2, "link", "-I", args.android_jar, "--manifest",
         source / "AndroidManifest.xml", "-o", unsigned])
    with zipfile.ZipFile(unsigned, "a") as apk:
        for file in sorted(dex.glob("classes*.dex")):
            apk.write(file, file.name, compress_type=zipfile.ZIP_DEFLATED)
    aligned = output / "aligned.apk"
    run([args.zipalign, "-p", "4", unsigned, aligned])
    final = output / "M19X6-Apps2SD-Link-Probe-1.0.apk"
    run([args.apksigner, "sign", "--key", args.key, "--cert", args.cert,
         "--v1-signing-enabled", "true", "--v2-signing-enabled", "true",
         "--out", final, aligned])
    run([args.apksigner, "verify", "--min-sdk-version", "29", final])
    with zipfile.ZipFile(final) as apk:
        if apk.testzip() is not None or "classes.dex" not in apk.namelist():
            raise ValueError("Probe APK contents failed verification")
    manifest = {
        "package": "xusu616.vormor.apps2sdprobe", "version": "1.0",
        "min_sdk": 29, "target_sdk": 29, "apk": final.name,
        "bytes": final.stat().st_size, "sha256": hashlib.sha256(final.read_bytes()).hexdigest(),
        "device_access": False, "installed": False,
        "storage_scope": "Only this probe's private launch_count preferences and apps2sd-probe.txt",
        "source_sha256": {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in [source / "AndroidManifest.xml", *sources]},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
