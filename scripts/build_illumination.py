#!/usr/bin/env python3
"""Compile the small Kotlin Camera1 flashlight app without changing Gradle."""
import argparse
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def run(args):
    result = subprocess.run([str(value) for value in args], check=False)
    if result.returncode:
        raise RuntimeError(f'Tool failed: {args[0]} ({result.returncode})')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('java', 'kotlin-compiler-cp', 'kotlin-stdlib', 'android-jar',
                 'aapt2', 'd8', 'zipalign', 'apksigner', 'key', 'cert', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    if output.exists():
        raise FileExistsError('Use a new output directory')
    output.mkdir(parents=True)
    source = ROOT / 'apps/illumination'
    jar = output / 'illumination.jar'
    separator = ';' if os.name == 'nt' else ':'
    run([args.java, '-cp', args.kotlin_compiler_cp,
         'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-no-stdlib', '-no-reflect',
         '-jvm-target', '1.8', '-classpath', args.android_jar + separator + args.kotlin_stdlib,
         '-d', jar, *sorted((source / 'src').glob('*.kt'))])
    dex = output / 'dex'
    dex.mkdir()
    run([args.d8, '--min-api', '29', '--lib', args.android_jar, '--output', dex, jar, args.kotlin_stdlib])
    unsigned = output / 'unsigned.apk'
    run([args.aapt2, 'link', '-I', args.android_jar, '--manifest', source / 'AndroidManifest.xml', '-o', unsigned])
    with zipfile.ZipFile(unsigned, 'a') as apk:
        for file in sorted(dex.glob('classes*.dex')):
            apk.write(file, file.name, compress_type=zipfile.ZIP_DEFLATED)
    aligned = output / 'aligned.apk'
    run([args.zipalign, '-p', '4', unsigned, aligned])
    final = output / 'M19X6-Illumination-1.1.apk'
    run([args.apksigner, 'sign', '--key', args.key, '--cert', args.cert,
         '--v1-signing-enabled', 'true', '--v2-signing-enabled', 'true',
         '--out', final, aligned])
    run([args.apksigner, 'verify', '--min-sdk-version', '29', final])
    print(final)


if __name__ == '__main__':
    main()
