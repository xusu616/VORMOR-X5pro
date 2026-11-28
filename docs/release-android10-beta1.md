# Android 10 beta1：M19_X6 / MT6580

## 成品和验证范围

本 Release 包含可复现的 PHH AOSP Android 10 v222 ARM32/Binder32、A-only 成品 system/boot、固定 ramdisk/平台兼容配置、参数化主机构建与首次安装脚本。保留 M19_X6 原 Linux 3.18.79 内核和 DTB，不替换本人 vendor、preloader、校准或原 userdata。

第八版基础配置已实机进入桌面并多次正常重启。发布 boot 另将 nvdata owner 改为运行时 serial，并允许 SD 没有第三分区；这些通用化差异已完成主机 CPIO/kernel/DTB 对比，未直接刷发布 boot 实测。因此标记 beta，不等同于全部同名设备通用。

system 壁纸修正已在实机验证并通过重启：Mali-400 不支持 EGL_IMG_context_priority，SystemUI 不再请求该扩展。网页测试实际显示 Chromium 141.0.7366.2，relro 1/1，现代 JavaScript API 检查通过。

## 下载什么

1. 成品刷机：下载 `VORMOR-X5pro-Android10-beta1-ROM.zip` 与 `VORMOR-X5pro-Android10-beta1-Scripts.zip`，核对 `SHA256SUMS`。
2. WebView 更新：下载 `webview-aosp-141.0.7366.2-arm-gsi-testkey.apk`；ROM 内基础 WebView 仍为74，在启动后 `adb install -r` 更新。
3. 单独壁纸修正：`SystemUI-M19X6-EGL-compatible.apk`，ROM 已包含；不能按普通应用安装。
4. 统一 Magisk Root：可选 `M19X6-Magisk-only-su-v1.1.zip`，在 Magisk 模块页面从本地 ZIP 安装。它停 PHH sudaemon并将标准 su 交给 Magisk，不卸载/清应用；禁用或移除模块后重启恢复PHH。
5. 主机重建：另下载匹配的 `M19X6-Android81-Magisk30.6-base-boot.img` 和 `magiskboot-windows.exe`，从README链接获取原 PHH v222 system。

不含私有 userdata/cache、nvdata 克隆、NVRAM/校准、预授权 ADB keys、照片或设备日志。请本人生成空白 SD data/cache。

## 首次安装

只支持核对过的 M19_X6 vendor/内核/DTB/GPT。设备需可用的匹配TWRP；先保存本人完整恢复资料。Windows使用pwsh、Python3.10+、ADB与WSL e2fsprogs。

```powershell
$py="python"
$adb="adb"
$serial="你自己的ADB序列号"
& $py .\scripts\prepare_sd.py --output-dir D:\a10-empty --wsl-distro Ubuntu
# TWRP取消system/data/cache和原sdcard bind挂载；保留external_sd。
& $py .\scripts\flash_android10.py --adb $adb --serial $serial --create-backup D:\a10-private-backup
& $py .\scripts\flash_android10.py --adb $adb --serial $serial --rom-dir D:\a10-rom --sd-images-dir D:\a10-empty --backup-dir D:\a10-private-backup
& $py .\scripts\flash_android10.py --adb $adb --serial $serial --rom-dir D:\a10-rom --sd-images-dir D:\a10-empty --backup-dir D:\a10-private-backup --result-dir D:\a10-install-result --flash --ack-m19-x6
& $adb -s $serial reboot
```

默认只读计划。--flash才写boot/system；拒绝覆盖已有SD测试镜像，不清空原userdata，不自动重启。SD第一分区FAT32，数据镜像2GiB、缓存128MiB；**启动依赖这张SD卡**。已有测试系统需另做保留数据的升级，不能删除旧镜像来通过首次安装助手。

## APK安装

WebView：

```powershell
& $adb -s $serial install -r .\webview-aosp-141.0.7366.2-arm-gsi-testkey.apk
& $adb -s $serial shell dumpsys webviewupdate
```

确认provider141.0.7366.2和relro1/1，实际打开网页。此APK为AOSP预编译按本GSI公开testkey重签，不是Google签名，不能用于签名不同的原厂ROM。

SystemUI：persistent系统应用，`adb install -r`会被Android10拒绝。ROM已包含兼容版；单独修正请进入TWRP，备份`/system/product/priv-app/SystemUI/SystemUI.apk`，将附件替换到相同路径，权限0644、owner0:0、SELinux `u:object_r:system_file:s0`；验证SHA后卸载system并正常启动。完整原生命令见README，不需要清壁纸或SystemUI数据。

## 修正内容

- 清除原vendor LD_PRELOAD，避免旧库干扰Q APEX引导。
- 真实apexd ready门控netd/zygote，消除DNS resolver未挂载的启动竞态。
- SD宿主位于`/mnt/vendor/a10-test`，避开vold清理仍使用的挂载。
- data/cache loop生命周期检查及autoclear；原用户和校准块只读。
- nvdata使用本人原数据的隔离可写克隆，音效使用原厂ABI匹配的VNDK27 parser。
- 壁纸EGL修正、WebView更新和可选Magisk-only Root模块。

## 已知问题

基础 ROM 的相机后置预览被报告上下倒置180°，后续独立 APK 已修正 BACK 预览矩阵并获用户确认。基础 SystemUI 在低于288dp时打开电源菜单会因默认尺寸缺失崩溃；后续 overlay 已恢复正常菜单及截图入口。这两项尚未加入基础 ROM。没有全面验证扫描头、无线硬件、实际音频输出或长期可靠性。Magisk直接安装的选项不解决双su，需要可选模块统一；PHH界面应用可保留且不影响停用底层daemon。不要使用完全卸载/Format Data解决适配问题。

底包固定SHA、重建命令、BCB进入REC/系统、照片媒体扫描与回退边界见README。工具/文件系统时间戳可能使重建整体SHA不同，具体输入/内容和文件系统检查记录仍完整。

## 补充：Root管理器与界面隐藏

`Magisk-v30.6.apk` 为官方原始管理器APK，附件SHA与官方Release digest一致。新空白data需自行安装管理器，再按README准备Magisk环境。模块v1.1使用指向正在运行Magisk的真实命令链接，修正旧布局仍触发“其他su”的提示；不修改Magisk检测代码。

隐藏PHH Superuser入口：`adb shell pm disable-user --user 0 me.phh.superuser`。仅停用UI包，不删除应用数据。恢复：`adb shell pm enable --user 0 me.phh.superuser`。本机已执行并确认没有桌面Activity，PHH daemon stopped、标准su仍是MAGISKSU。

## 补充：Apps2SD p3 与 APK 链接

补充源码包含按本人 SD 身份生成 Magisk 早期挂载模块的脚本、Apps2SD 16 外部挂载配置脚本和独立 Kotlin 验证应用。仅格式化本机已明确指定的 p3；p1 上正在使用的 Android 10 data/cache 和 p2 保留，分区表、p1 首扇区与 p2 的前后校验一致。

独立验证包已经通过 APK 链接与正常重启，原路径指向 `/data/sdext2/apk/`，APK 与测试文件校验保持一致，内部计数跨重启保留。只验证 APK；Data、ODEX、lib 和关键系统应用链接不在本次实测范围。每张卡的 CID/UUID 配置与生成模块仅保留本人私有，不上传通用附件。详见 `docs/apps2sd-external-mount.md`。

## 补充：相机预览APK

`Camera2-M19X6-rear-preview180.apk` 仅用于本PHH v222相机。安装：`adb install -r --no-incremental Camera2-M19X6-rear-preview180.apk`，保留相机数据。最终修正在 `CaptureModule.updatePreviewTransform(int,int,boolean)` 对 `mCameraFacing == BACK` 的矩阵追加 `postRotate(180, width/2, height/2)`，前置、getPreviewOrientation 和 JPEG方向方法不变。使用者已确认前后预览正常，此前JPEG正向（Orientation=1）；触摸对焦、横屏和视频仍需验证。它不是全局相机HAL修复。APK SHA：`48c8ce73270bdbc5bf54c8fa9f85430ed6e61b9ffe5ca8e4c43b25ff5eb6147a`。完整安装与主机重建见[相机说明](camera-preview-experiment.md)。

`VORMOR-X5pro-Android10-beta1-Extras.zip` 保存后续Root界面隐藏说明、相机脚本与当前使用文档。基础ROM和其原SHA不变；新补充文件核对`SHA256SUMS-extras`。

## 补充：截图菜单资源覆盖

`SystemUI-M19X6-small-width-overlay.apk` 只补齐 PHH v222 在低于288dp时缺失的11个电源菜单尺寸；本机272dp界面不再因 InflateException 回退到没有截图的 Legacy 菜单。已观察到“屏幕截图”入口恢复。它是独立 overlay，基础 ROM 尚未包含。

```powershell
& $adb -s $serial install -r --no-incremental .\SystemUI-M19X6-small-width-overlay.apk
& $adb -s $serial shell cmd overlay enable --user 0 xusu616.vormor.systemui.smallwidth
& $adb -s $serial shell cmd overlay list --user 0
```

包名 `xusu616.vormor.systemui.smallwidth`，无桌面图标。SHA：`c554f09b7cb271c398207327997dd53159ae65f769e7f4c7c77f959f4368b802`。禁用该 overlay 可撤销，不清 SystemUI 数据；构建和验证见[截图菜单说明](screenshot-menu-overlay.md)。

## 补充：照明应用1.1

`M19X6-Illumination-1.1.apk` 使用原厂 legacy camera1 torch 通道，不要求Root。用 `adb install -r --no-incremental M19X6-Illumination-1.1.apk` 安装，打开“词典笔照明”允许相机权限，在快捷设置编辑页添加“照明”。应用按钮、通知或磁贴可以开关；开灯占用camera1，关闭后释放。

v1.1已实机替换安装并保留数据，磁贴off→on→off与驱动FLASHLIGHT ENABLE/DISABLE对应，用户确认修复。后续HAL断开时停止服务并更新状态，不自动重试。SHA：`143f85cb8f9447bd34ae8e0c22b4c3f0fe48e34e33ebd97e23fbb86046399b58`。源代码、Kotlin主机编译命令和已知限制见[照明说明](illumination.md)。

以上后续 APK 与资源源文件属于独立补充，未加入基础 beta1 ROM，不改变其 system/boot SHA。它们不包含 SD p3 格式化或原 Apps2SD 数据迁移；该存储操作需另行备份、确认具体分区并独立验证，不作为此 Release 已完成结果。
