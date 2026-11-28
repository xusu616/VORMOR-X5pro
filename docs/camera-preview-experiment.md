# Camera2 后置预览 180° 修正

2026-11-28：`Camera2-M19X6-rear-preview180.apk` 是针对本项目 PHH v222 Camera2 的独立预览修正。用户已确认前、后两路预览方向正常。它未加入基础 `VORMOR-X5pro-Android10-beta1-ROM.zip`，该 ROM 仍保留原 Camera2。

## 最终修改范围

原厂 legacy HAL 的两个镜头报告 orientation=270，内置 Camera2 的后置预览被观察为上下颠倒。全局 HAL 方向差异尚未确定；最终补丁仅在 `com.android.camera.CaptureModule.updatePreviewTransform(int,int,boolean)` 中，对 `mCameraFacing == OneCamera.Facing.BACK` 的预览矩阵追加 `Matrix.postRotate(180f, mScreenWidth / 2f, mScreenHeight / 2f)`，然后走原有的 `AppController` 预览变换流程。

前置路径不追加旋转。`getPreviewOrientation`、`getJpegOrientation`、sensor orientation 和 vendor/内核配置保持不变。此前保存的 JPEG 已观察为正向、EXIF Orientation=1，因此补丁不再改变拍照方向。它只影响内置 Camera2 的这一预览路径，不能代替其他扫描 App 的方向适配。

不再使用早期“所有镜头的 getPreviewOrientation 返回值加180°”试验包；最终脚本与附件是后置矩阵修正。

| 文件 | SHA-256 |
| --- | --- |
| PHH v222 `Camera2-original.apk` | `6a66cacff704ab1722373e505fe92f53c66df29e66858cd791a6957be0be367d` |
| `Camera2-M19X6-rear-preview180.apk` | `48c8ce73270bdbc5bf54c8fa9f85430ed6e61b9ffe5ca8e4c43b25ff5eb6147a` |
| 官方 apktool 3.0.3 JAR | `dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423` |

## 安装与验证

在相同 PHH v222 系统上用替换安装保留相机数据；无需 Root、清相机数据或更改全局旋转：

```powershell
$adb = "adb"
$serial = "你自己的ADB序列号"
& $adb -s $serial install -r --no-incremental .\Camera2-M19X6-rear-preview180.apk
```

打开相机并分别检查前置、后置。继续验证触摸对焦位置、横屏、拍照文件和视频；这些尚未全面验证。开着[照明应用](illumination.md)时它会占用 camera1，先关闭照明以免相机打开失败。

该 APK 为与本 ROM 相同的 AOSP testkey 签名。不要装到签名或底包不同的原厂系统；不要卸载系统相机来绕过签名检查。要恢复原预览，保留原 APK 并按同签名替换恢复；若系统拒绝版本降级，使用匹配 TWRP 恢复原系统 Camera2 文件，保留应用数据。

## 在主机重建

脚本 `scripts/patch_camera_preview.py` 检查固定原 APK 哈希、精确方法和插入锚点，拒绝重复修改。只改 `smali/com/android/camera/CaptureModule.smali` 的一个方法；其前后内容逐字节保留。

准备 Java、官方 apktool 3.0.3、Android SDK build-tools 和与原 APK 匹配的本 ROM testkey。以下工作全部在 PC，新解码目录不能复用其他实验结果：

```powershell
$py = "python"
$apktool = ".\apktool_3.0.3.jar"
$buildTools = "C:\Android\Sdk\build-tools\36.0.0"

java -jar $apktool d -r -o D:\camera-rear-decoded .\Camera2-original.apk
& $py .\scripts\patch_camera_preview.py `
  --source-apk .\Camera2-original.apk --decoded-dir D:\camera-rear-decoded
java -jar $apktool b -o D:\Camera2-rear-unsigned.apk D:\camera-rear-decoded
& "$buildTools\zipalign.exe" -p 4 D:\Camera2-rear-unsigned.apk D:\Camera2-rear-aligned.apk
& "$buildTools\apksigner.bat" sign --key .\testkey.pk8 --cert .\testkey.x509.pem `
  --v1-signing-enabled true --v2-signing-enabled true `
  --out D:\Camera2-M19X6-rear-preview180.apk D:\Camera2-rear-aligned.apk
& "$buildTools\apksigner.bat" verify --min-sdk-version 29 --print-certs D:\Camera2-M19X6-rear-preview180.apk
```

重建工具的 DEX 打包细节可能改变整体 APK SHA；应检查最终方法只对 BACK 追加旋转、前置与 JPEG 方法未改、原始资源和 manifest 保留，并确认签名证书匹配。基础 ROM/boot 的哈希和 SD 分区没有因为这个 APK 改动而改变。
