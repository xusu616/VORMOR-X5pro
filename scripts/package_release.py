#!/usr/bin/env python3
"""Package explicit public inputs; never include private audits or userdata."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import zipfile

REPO = Path(__file__).resolve().parent.parent


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def add_file(z: zipfile.ZipFile, source: Path, name: str, executable=False):
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'Not an explicit regular input: {source}')
    info = zipfile.ZipInfo(name, (2026, 11, 28, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    with source.open('rb') as src, z.open(info, 'w', force_zip64=True) as dst:
        shutil.copyfileobj(src, dst, 1048576)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('boot', 'system', 'base-boot', 'systemui', 'webview', 'magiskboot', 'output-dir'):
        p.add_argument('--' + key, type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        raise FileExistsError('Use a new release output directory')
    expected = {
        'boot': '19c8be711498b4a64eeba3797a8364a66d4c2667f8d7efbac64a988dd7090738',
        'system': 'c442160ccc0ec45b5e3706dff8f1210b85e9a793c5df3a4ef3882bebb809387c',
        'base_boot': '8aee6807955c700946a031837266ba0364c549b6a150374cac4fab924d21c35b',
        'systemui': '226c3de42b08069a7053abcb93a620c8d6c2510b43294407857e1053a1d3a4cb',
        'webview': '47e3a1d35db7846dc101cd16b3ae2f88bbc99d0f161d5a91071beb2375b9286c',
        'magiskboot': '2d3f9dcdbf6fd9b8a5c8ab333c7434f43d8916ab29da81d6f9dc37f0731e8ea2',
    }
    for key, sha in expected.items():
        if digest(getattr(a, key)) != sha:
            raise ValueError(f'Public input hash mismatch: {key}')
    if a.boot.stat().st_size != 16777216 or a.system.stat().st_size != 1131864064:
        raise ValueError('Wrong image sizes')
    a.output_dir.mkdir(parents=True)
    rom_manifest = {
        'format': 'vormor-a10-rom-v1', 'release': 'android10-beta1-20261128',
        'board': 'M19_X6', 'soc': 'MT6580', 'android': '10', 'binder': '32',
        'images': {key: {'name': key + '.img', 'bytes': getattr(a, key).stat().st_size,
                         'sha256': expected[key]} for key in ('boot', 'system')},
        'requires_own_vendor_and_sd': True,
        'includes_userdata': False,
        'validation': 'trial8 core configuration boot/reboot tested; public boot adaptations host verified; SystemUI patch live and reboot tested',
    }
    manifest_path = a.output_dir / 'rom-manifest.json'
    manifest_path.write_text(json.dumps(rom_manifest, indent=2) + '\n', encoding='utf-8')
    rom_zip = a.output_dir / 'VORMOR-X5pro-Android10-beta1-ROM.zip'
    with zipfile.ZipFile(rom_zip, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for key in ('boot', 'system'):
            add_file(z, getattr(a, key), key + '.img')
        add_file(z, manifest_path, 'rom-manifest.json')
        add_file(z, REPO / 'README.md', 'README.md')
        add_file(z, REPO / 'docs/release-android10-beta1.md', 'RELEASE-NOTES.md')
    with zipfile.ZipFile(rom_zip) as z:
        if z.testzip() is not None:
            raise ValueError('ROM ZIP CRC check failed')
        for key in ('boot', 'system'):
            h = hashlib.sha256()
            with z.open(key + '.img') as f:
                for chunk in iter(lambda: f.read(1048576), b''):
                    h.update(chunk)
            if h.hexdigest() != expected[key]:
                raise ValueError(f'ZIP image readback mismatch: {key}')
    print('ROM ZIP payload hashes and CRC checked.', flush=True)
    scripts_zip = a.output_dir / 'VORMOR-X5pro-Android10-beta1-Scripts.zip'
    with zipfile.ZipFile(scripts_zip, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for root in ('scripts', 'configs', 'modules'):
            for source in sorted((REPO / root).rglob('*')):
                if source.is_file() and '__pycache__' not in source.parts and source.suffix != '.pyc':
                    name = source.relative_to(REPO).as_posix()
                    add_file(z, source, name, source.suffix in ('.py', '.sh') or source.name == 'update-binary')
        for name in ('README.md', 'LICENSE', 'docs/release-android10-beta1.md', 'docs/webview-render-check.html'):
            add_file(z, REPO / name, name)
    module_root = REPO / 'modules/m19x6-magisk-only'
    module_zip = a.output_dir / 'M19X6-Magisk-only-su-v1.1.zip'
    with zipfile.ZipFile(module_zip, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for source in sorted(module_root.rglob('*')):
            if source.is_file():
                add_file(z, source, source.relative_to(module_root).as_posix(),
                         source.suffix == '.sh' or source.name == 'update-binary')
    copies = {
        'M19X6-Android81-Magisk30.6-base-boot.img': a.base_boot,
        'boot-VORMOR-X5pro-Android10-beta1.img': a.boot,
        'SystemUI-M19X6-EGL-compatible.apk': a.systemui,
        'webview-aosp-141.0.7366.2-arm-gsi-testkey.apk': a.webview,
        'magiskboot-windows.exe': a.magiskboot,
    }
    for name, source in copies.items():
        shutil.copyfile(source, a.output_dir / name)
    # rom-manifest.json belongs in the ROM ZIP, not a duplicate public attachment.
    manifest_path.unlink()
    assets = [{'name': f.name, 'bytes': f.stat().st_size, 'sha256': digest(f)}
              for f in sorted(a.output_dir.iterdir()) if f.is_file()]
    public = {'release': 'android10-beta1-20261128', 'assets': assets,
              'images': rom_manifest['images'], 'no_private_device_data': True,
              'known_issues': ['camera preview orientation', 'third-party modules need individual validation'],
              'source_refs': {'phh': 'v222', 'magisk': 'v30.6', 'webview': 'AOSP prebuilt 141.0.7366.2 re-signed for GSI testkey'}}
    release_manifest = a.output_dir / 'release-manifest.json'
    release_manifest.write_text(json.dumps(public, indent=2) + '\n', encoding='utf-8')
    files = sorted(f for f in a.output_dir.iterdir() if f.is_file())
    (a.output_dir / 'SHA256SUMS').write_text(''.join(digest(f) + '  ' + f.name + '\n' for f in files), encoding='ascii')
    print(json.dumps(public, indent=2), flush=True)


if __name__ == '__main__':
    main()
