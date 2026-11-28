# M19_X6 照明应用 1.1

`M19X6-Illumination-1.1.apk` 是本项目独立 Kotlin 应用，包名 `xusu616.vormor.illumination`，minSDK／targetSDK29。它不需要 Root，未加入基础 beta1 ROM。当前 APK SHA-256：`143f85cb8f9447bd34ae8e0c22b4c3f0fe48e34e33ebd97e23fbb86046399b58`。

这台设备的 Camera2 torch 接口没有为 camera1 声明闪光灯；应用使用原厂 legacy `Camera.open(1)`、预览 SurfaceTexture 和 `FLASH_MODE_TORCH` 通道。开灯期间必须保持前台服务和相机连接，所以会占用该镜头；关闭后释放。只支持本机已识别的通道，不能作为所有 Android 相机的通用手电筒。

## 安装与使用

```powershell
$adb = "adb"
$serial = "你自己的ADB序列号"
& $adb -s $serial install -r --no-incremental .\M19X6-Illumination-1.1.apk
```

打开“词典笔照明”，允许相机权限，点“打开照明”。用应用“关闭照明”按钮或前台通知中的“关闭”释放镜头。快捷设置编辑页可添加“照明”磁贴；磁贴需要解锁后切换，未授权时会打开应用申请权限。

v1.1 的磁贴从服务的实际开启状态读取，不在点击时自行翻转。服务开启成功、关闭并释放时请求更新；manifest 的 `ACTIVE_TILE=true` 使 Android10 接受这些更新。HAL 连接错误会提示并停止服务，由统一销毁路径释放资源，不自动循环重试。设备重启后不自动开灯。

本机 v1.1 已用 `adb install -r` 替换并保留应用数据，快捷磁贴 off→on→off 日志与驱动 `FLASHLIGHT ENABLE/DISABLE` 对应，用户确认开关修复。其他设备仍需核对物理 LED、关闭后镜头释放，以及磁贴／通知状态。遇到相机占用错误，先关闭相机 App；不要清相机或照明应用数据。

## 在 PC 构建

源文件在 `apps/illumination/src/`，manifest 在同目录；`scripts/build_illumination.py` 调用 Kotlin 编译器、D8、aapt2、zipalign 和 apksigner，不修改项目 Gradle。准备 Java、Kotlin命令行发行包、Android29 android.jar 和 SDK build-tools。`--kotlin-compiler-cp` 传给Java的classpath，使用Kotlin发行包 `lib/*` 会包含编译器及其运行依赖。

```powershell
$py = "python"
$java = "java"
$kotlinHome = "C:\Kotlin\kotlinc"
$kotlinCompilerCp = "$kotlinHome\lib\*"
$kotlinStdlib = "$kotlinHome\lib\kotlin-stdlib.jar"
$androidJar = "C:\Android\Sdk\platforms\android-29\android.jar"
$buildTools = "C:\Android\Sdk\build-tools\36.0.0"

& $py .\scripts\build_illumination.py --java $java `
  --kotlin-compiler-cp $kotlinCompilerCp --kotlin-stdlib $kotlinStdlib `
  --android-jar $androidJar --aapt2 "$buildTools\aapt2.exe" `
  --d8 "$buildTools\d8.bat" --zipalign "$buildTools\zipalign.exe" `
  --apksigner "$buildTools\apksigner.bat" `
  --key .\testkey.pk8 --cert .\testkey.x509.pem --output-dir D:\illumination-build
```

输出目录必须不存在，最终文件为 `M19X6-Illumination-1.1.apk`。脚本验证 API29 签名；工具版本可能改变整体 APK SHA。发布包使用本 ROM 的 AOSP testkey，证书 SHA-256 `a40da80a59d170caa950cf15c18c454d47a39b26989d8b640ecd745ba71bf5dc`。自行改用其他证书后不能直接替换已安装的发布包，不要通过卸载丢失数据来回避证书差异。

后续 APK 的独立补充不改变 beta1 ROM 的 system／boot 哈希。本文不提供 SD 第三分区格式化或 Apps2SD 迁移命令；该存储操作属于单独备份和核验后的流程。
