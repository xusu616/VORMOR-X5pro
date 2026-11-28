#!/usr/bin/env python3
"""Experimental rear CaptureModule TextureView +180 patch for PHH Camera2.

Decode the original APK with apktool -r first. This changes one exact smali
transform method, preserving JPEG/preview angles and the front camera. Rebuild,
ZIP-align and sign with the ROM's AOSP testkey afterwards. Not a HAL fix.
"""
import argparse
import hashlib
from pathlib import Path
import re

SOURCE_SHA = '6a66cacff704ab1722373e505fe92f53c66df29e66858cd791a6957be0be367d'
MEMBER = 'smali/com/android/camera/CaptureModule.smali'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-apk', type=Path, required=True)
    p.add_argument('--decoded-dir', type=Path, required=True)
    a = p.parse_args()
    if hashlib.sha256(a.source_apk.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError('Camera2 APK differs from the pinned v222 source')
    f = a.decoded_dir / MEMBER
    source = f.read_text(encoding='utf-8')
    block = re.search(r'(?ms)^\.method private updatePreviewTransform\(IIZ\)V\n.*?^\.end method$', source)
    if block is None:
        raise ValueError('Exact CaptureModule preview transform method missing')
    code = block.group(0)
    anchor = ('    move-result-object p1\n\n'
              '    .line 1260\n'
              '    iget-object p0, p0, Lcom/android/camera/CaptureModule;->mAppController:Lcom/android/camera/app/AppController;')
    if code.count('    .locals 3') != 1 or code.count(anchor) != 1:
        raise ValueError('Unexpected CaptureModule transform control flow')
    if '->postRotate(' in code or 'codex_preview' in code:
        raise ValueError('Preview method was already modified')
    change = (
        '    move-result-object p1\n\n'
        '    iget-object v1, p0, Lcom/android/camera/CaptureModule;->mCameraFacing:Lcom/android/camera/one/OneCamera$Facing;\n'
        '    sget-object v2, Lcom/android/camera/one/OneCamera$Facing;->BACK:Lcom/android/camera/one/OneCamera$Facing;\n'
        '    if-ne v1, v2, :codex_preview_matrix_ready\n\n'
        '    iget v1, p0, Lcom/android/camera/CaptureModule;->mScreenWidth:I\n'
        '    int-to-float v1, v1\n'
        '    const/high16 v2, 0x40000000  # 2.0f\n'
        '    div-float/2addr v1, v2\n'
        '    iget p2, p0, Lcom/android/camera/CaptureModule;->mScreenHeight:I\n'
        '    int-to-float p2, p2\n'
        '    div-float/2addr p2, v2\n'
        '    const/high16 p3, 0x43340000  # 180.0f\n'
        '    invoke-virtual {p1, p3, v1, p2}, Landroid/graphics/Matrix;->postRotate(FFF)Z\n'
        '    const-string v1, "M19_CameraPreview"\n'
        '    const-string v2, "rear TextureView rotated 180"\n'
        '    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I\n\n'
        '    :codex_preview_matrix_ready\n'
        '    .line 1260\n'
        '    iget-object p0, p0, Lcom/android/camera/CaptureModule;->mAppController:Lcom/android/camera/app/AppController;'
    )
    altered = code.replace(anchor, change, 1)
    result = source[:block.start()] + altered + source[block.end():]
    # Everything before/after this exact method remains byte-for-byte.
    if source[:block.start()] != result[:block.start()] or not result.endswith(source[block.end():]):
        raise ValueError('Unrelated CaptureModule contents changed')
    f.write_text(result, encoding='utf-8', newline='\n')
    print('Only CaptureModule rear preview matrix changed; original orientation/JPEG getters remain untouched. Build and sign are still required.')


if __name__ == '__main__':
    main()
