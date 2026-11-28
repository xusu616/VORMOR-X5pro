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

相机可用但预览被报告上下倒置180°，尚未修正。没有全面验证扫描头、无线硬件、实际音频输出或长期可靠性。Magisk直接安装的选项不解决双su，需要可选模块统一；PHH界面应用可保留且不影响停用底层daemon。不要使用完全卸载/Format Data解决适配问题。

底包固定SHA、重建命令、BCB进入REC/系统、照片媒体扫描与回退边界见README。工具/文件系统时间戳可能使重建整体SHA不同，具体输入/内容和文件系统检查记录仍完整。
