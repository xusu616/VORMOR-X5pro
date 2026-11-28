"""Remove unsupported IMG context priority from the pinned Q SystemUI APK.

The M19_X6 Mali-400 driver advertises no EGL_IMG_context_priority extension.
The pinned EglHelper.createEglContext requests it unconditionally. Terminate
its attribute array immediately after EGL_CONTEXT_CLIENT_VERSION, 2.
APK signing and zip alignment must be performed after this transformation.
"""
import argparse
import hashlib
from pathlib import Path
import struct
import zipfile
import zlib

SOURCE_SHA = 'defbee195c3590cfc458fb26d5cbbe9fa78e146b9b4ae7e51fabfb67b17ddf75'
CLASS_NAME = 'Lcom/android/systemui/glwallpaper/EglHelper;'
METHOD_NAME = 'createEglContext'
ARRAY = struct.pack('<HHI5I', 0x0300, 4, 5, 0x3098, 2, 0x3100, 0x3103, 0x3038)


def uleb(data, pos):
    value = 0
    for shift in range(0, 35, 7):
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ValueError('Invalid DEX ULEB128')


def method_code(data):
    string_count, string_off = struct.unpack_from('<II', data, 56)
    strings = []
    for index in range(string_count):
        offset = struct.unpack_from('<I', data, string_off + index * 4)[0]
        _, offset = uleb(data, offset)
        end = data.index(0, offset)
        strings.append(data[offset:end].decode('utf-8', errors='replace'))
    type_count, type_off = struct.unpack_from('<II', data, 64)
    types = [strings[struct.unpack_from('<I', data, type_off + i * 4)[0]]
             for i in range(type_count)]
    _, method_off = struct.unpack_from('<II', data, 88)
    class_count, class_off = struct.unpack_from('<II', data, 96)
    for index in range(class_count):
        offset = class_off + index * 32
        class_index = struct.unpack_from('<I', data, offset)[0]
        if types[class_index] != CLASS_NAME:
            continue
        pos = struct.unpack_from('<I', data, offset + 24)[0]
        counts = []
        for _ in range(4):
            value, pos = uleb(data, pos)
            counts.append(value)
        for _ in range(counts[0] + counts[1]):
            _, pos = uleb(data, pos)
            _, pos = uleb(data, pos)
        matches = []
        for count in counts[2:]:
            method_index = 0
            for _ in range(count):
                delta, pos = uleb(data, pos)
                method_index += delta
                _, pos = uleb(data, pos)
                code_off, pos = uleb(data, pos)
                declaring_class, _, name_index = struct.unpack_from('<HHI', data, method_off + method_index * 8)
                if declaring_class == class_index and strings[name_index] == METHOD_NAME:
                    size = struct.unpack_from('<I', data, code_off + 12)[0]
                    matches.append((code_off + 16, code_off + 16 + size * 2))
        if len(matches) != 1:
            raise ValueError('Expected one exact EglHelper.createEglContext method')
        return matches[0]
    return None


def patch_dex(source):
    code = method_code(source)
    if code is None:
        return None
    start, end = code
    offset = source.find(ARRAY, start, end)
    if offset < 0 or source.find(ARRAY, offset + 1, end) >= 0:
        raise ValueError('Expected one priority attribute array inside the exact method')
    result = bytearray(source)
    # Array header is 8 bytes, then CLIENT_VERSION and its value are 8 bytes.
    struct.pack_into('<I', result, offset + 16, 0x3038)
    result[12:32] = hashlib.sha1(result[32:]).digest()
    struct.pack_into('<I', result, 8, zlib.adler32(result[12:]) & 0xffffffff)
    if len(result) != len(source):
        raise ValueError('DEX byte length changed')
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_apk', type=Path)
    parser.add_argument('unsigned_apk', type=Path)
    args = parser.parse_args()
    if hashlib.sha256(args.source_apk.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError('SystemUI source differs from the pinned PHH v222 APK')
    if args.unsigned_apk.exists():
        raise FileExistsError('Refusing to overwrite an existing output')
    patched = 0
    with zipfile.ZipFile(args.source_apk) as src:
        payloads = []
        for info in src.infolist():
            if info.filename.startswith('META-INF/'):
                continue
            content = src.read(info)
            if info.filename.endswith('.dex'):
                replacement = patch_dex(content)
                if replacement is not None:
                    content = replacement
                    patched += 1
            payloads.append((info, content))
        if patched != 1:
            raise ValueError('Expected one patched DEX member')
        with zipfile.ZipFile(args.unsigned_apk, 'x') as dst:
            for info, content in payloads:
                dst.writestr(info, content)
    print('Patched only EglHelper.createEglContext. ZIP alignment and signing are still required.')


if __name__ == '__main__':
    main()
