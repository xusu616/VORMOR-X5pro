# VORMOR X5pro / M19_X6 Android 10 移植

本项目将 PHH AOSP Android 10 v222 与 M19_X6 原机 Android 8.1 vendor、Linux 3.18.79 内核和 DTB 配合使用。它是实验性设备适配包，没有升级内核，也不是全部 X5pro 型号的通刷包。

[GitHub Releases](https://github.com/xusu616/VORMOR-X5pro_Android10/releases) · [GitLab Releases](https://gitlab.com/xusu616/VORMOR-X5pro/-/releases)

## 已验证与已知问题

2026-11-28：第八版底层配置实际进入 Android 10 桌面，并通过正常重启；触摸正常。WebView 141.0.7366.2 已实际加载、relro 完成，网页和现代 JavaScript API 验证通过。SystemUI 壁纸兼容修正已在设备实际加载，壁纸恢复，并通过重启；system 已恢复只读。

发布 boot 在已测试配置上另做两项通用化：使用本机运行时 serial 标记自己的 nvdata 克隆；SD 没有第三分区时不要求不存在的 Apps2SD 块设备。发布 boot 的这些差异通过主机重建/CPIO 对比，尚未直接刷入实测。因此 Release 标记为 **beta**，不要把本机第八版 SHA 当成发布 boot SHA。发布 system 已从公开 PHH 底包重新构建并只读 fsck 通过，含壁纸修正。

已知问题：

- 基础 ROM 的相机后置预览被报告倒置180°。后续独立 Camera2 APK 仅修正 BACK 预览矩阵，用户已确认前、后预览正常；横屏、触摸对焦和视频仍需验证。
- 小宽度下原 SystemUI 电源菜单会因缺少默认尺寸崩溃并回退到没有截图的 Legacy 菜单。独立资源 overlay 已恢复正常菜单和截图入口；基础 ROM 尚未包含它。
- GSI 自带 PHH Superuser 与 boot 中的 Magisk 30.6 同时存在。完整第三方模块兼容仍需逐个验证；本 Release 另提供可选 Magisk-only 模块统一标准 su 入口。
- 尚未全面验证扫描头、蓝牙、所有无线连接、扬声器实际输出和长期运行。
- 原 Android 8.1 应用数据不会自动迁移到新系统。新系统的 data/cache 位于独立 SD 镜像，**必须保留 SD 卡**。

## 底包、硬件和固定配置

| 项目 | 要求 |
| --- | --- |
| 主板 | M19_X6 / VORMOR X5pro；同名外壳不能代替主板确认 |
| SoC / ABI | MT6580，ARMv7，32 位 Binder |
| 原 vendor | Android 8.1 / API27；保留本人设备 vendor |
| 内核 | 原 Linux 3.18.79，非 GKI；不编译新内核 |
| PHH 底包 | v222 的 `system-quack-arm-aonly-vanilla.img.xz`，ARM32/Binder32、A-only、vanilla |
| boot 分区 | p8，16 MiB；offset 0x1d80000 |
| system 分区 | p21，5,477,761,024 字节；offset 0x25000000 |
| para / BCB | p10，512 KiB；offset 0x3d80000，承担 misc 的启动指令作用 |
| SD | 第一分区 FAT32，至少约 4 GiB 可用空间；data 2 GiB + cache 128 MiB |
| 本机显示参考 | physical 480×800；实际使用 override 340×800、200 dpi、字体 1.3 |

PHH 原包：[固定 v222 资产](https://github.com/phhusson/treble_experimentations/releases/download/v222/system-quack-arm-aonly-vanilla.img.xz)。SHA-256：

```text
c62c1456714cdd1201ee41b7fb5dd68862131e146f523ded721f86136fe481d6
```

不要选 ARM64、Binder64、A/B 或其他 Android 版本。`configs/profile.json` 固定原 boot、kernel、DTB、vendor CIL 和底包哈希；脚本不根据机型名称猜测兼容性。

## Release 附件

- `VORMOR-X5pro-Android10-beta1-ROM.zip`：`boot.img`、raw `system.img`、`rom-manifest.json` 与使用说明。只写 boot/system；不含 vendor、preloader 或个人校准区。
- `VORMOR-X5pro-Android10-beta1-Scripts.zip`：本 README、脚本、固定配置和兼容库。
- `M19X6-Android81-Magisk30.6-base-boot.img`：用于主机重建的匹配基底，已含 Magisk，不是未经修改的原厂 boot，也不是给不同 vendor 设备恢复用的镜像。
- `SystemUI-M19X6-EGL-compatible.apk`：仅用于本 PHH v222 system 的壁纸修正；ROM 已包含它。
- `webview-aosp-141.0.7366.2-arm-gsi-testkey.apk`：API29/ARMv7 的 WebView 更新。
- `magiskboot-windows.exe`：此次重建使用的 Windows 移植工具；来源见下文。
- `M19X6-Magisk-only-su-v1.1.zip`：可选 Magisk 模块，停用 PHH daemon并统一标准 su 入口。
- 后续独立补充：`Camera2-M19X6-rear-preview180.apk`、`SystemUI-M19X6-small-width-overlay.apk`、`M19X6-Illumination-1.1.apk`，用法见下文；基础 beta1 ROM 不含这三个 APK。
- `SHA256SUMS`、`release-manifest.json`：附件校验与验证范围。

先下载同一 Release 的文件并核对 SHA256SUMS。镜像放 Release，不放 Git 历史。**不发布** nvram/nvdata、个人 GPT/BCB 快照、测试 userdata/cache、预授权 ADB keys、个人照片或设备日志。历史备份仓库曾有 NVRAM 提交；本次没有改写那段历史。

## 使用成品：第一次安装

需要在设备旁操作：已有可用且匹配硬件的 TWRP、本人原固件恢复备份、USB 线和 FAT32 SD 卡。原仓库的仅 PRELOADER scatter 不是完整线刷方案。不要 Format Data、Wipe 原 userdata，或为了首启清空应用。

在 Windows pwsh 准备 Python 3.10+、Android platform-tools，并配置已有 WSL 发行版的 e2fsprogs；例如 Ubuntu 中安装 `e2fsprogs`。解压 ROM 到 `D:\a10-rom`、Scripts 到项目目录。

```powershell
$py = "python"
$adb = "adb"
& $adb devices -l
$serial = "填写你自己的ADB序列号"

# 只在电脑新建空白文件；不格式化 SD、不复制任何人的授权或校准。
& $py .\scripts\prepare_sd.py --output-dir D:\a10-empty --wsl-distro Ubuntu
```

进入 TWRP。保留 SD 的 `/external_sd` 挂载；在 Mount 页面取消 system/data/cache，并检查 `adb shell cat /proc/mounts`，原 userdata 的 `/sdcard` bind 也需卸载。脚本遇到原分区仍挂载会停止，不会自行 Wipe。

```powershell
# 私有备份会读取本人完整 boot/system；需约 6 GiB 电脑空间并保持连接。
& $py .\scripts\flash_android10.py --adb $adb --serial $serial `
  --create-backup D:\a10-private-backup

# 默认只读计划：核镜像、本人备份、TWRP 与 GPT 边界。
& $py .\scripts\flash_android10.py --adb $adb --serial $serial `
  --rom-dir D:\a10-rom --sd-images-dir D:\a10-empty `
  --backup-dir D:\a10-private-backup

# 明确写入 boot/system；result-dir 必须是新目录。
& $py .\scripts\flash_android10.py --adb $adb --serial $serial `
  --rom-dir D:\a10-rom --sd-images-dir D:\a10-empty `
  --backup-dir D:\a10-private-backup --result-dir D:\a10-install-result `
  --flash --ack-m19-x6

& $adb -s $serial reboot
```

这一步会上传新的空白 SD data/cache，拒绝覆盖已有 `.codex-android10-test` 文件。已有测试镜像中可能有应用和照片；不要为了通过脚本自行删除它们。首次安装助手不是已有试验系统的无损升级工具。完整救砖仍需本人 vendor、recovery、GPT、NVRAM/校准和必要 boot 区备份；它们仅保留本地。

首启后在设备允许自己的 USB 调试授权。参考显示设置可由本人明确执行，之后仍可自行调整：

```powershell
& $adb -s $serial shell wm size 340x800
& $adb -s $serial shell wm density 200
& $adb -s $serial shell settings put system font_scale 1.3
& $adb -s $serial shell getprop ro.build.version.sdk
& $adb -s $serial shell getprop sys.boot_completed
& $adb -s $serial shell getprop service.nvram_init
```

期望 SDK 29、boot_completed 1、nvram Ready；再测试一次正常重启。它使用的是新 SD data，并非原 userdata 的桌面/应用数据。

## APK 用法

### WebView 141

这是 AOSP 预编译包按本 ROM 的公开 testkey 重签，不是 Google 签名包；它的证书与本 GSI WebView 74 相同。不能用于签名不同的任意原厂 ROM，也不宣称是最新稳定版。

```powershell
& $adb -s $serial install -r .\webview-aosp-141.0.7366.2-arm-gsi-testkey.apk
& $adb -s $serial shell dumpsys webviewupdate
```

确认 Current WebView 为 `com.android.webview, 141.0.7366.2`，relro started/finished 均为 1，并实际打开网页。不要先卸载旧 WebView。测试 HTML 见 `docs/webview-render-check.html`；本机已用预装 WebView Shell 验证。

### 后续相机、截图菜单和照明补充

这三项独立 APK 不改变已经发布的基础 ROM、system／boot 哈希，使用与本 PHH v222 兼容的附件，安装时保留应用数据：

| 附件 | 作用和当前验证 | 使用／重建 |
| --- | --- | --- |
| `Camera2-M19X6-rear-preview180.apk` | 只对 CaptureModule 的 BACK 预览矩阵追加180°；用户确认前后预览正常，JPEG方向方法未改 | [相机预览说明](docs/camera-preview-experiment.md) |
| `SystemUI-M19X6-small-width-overlay.apk` | 补齐低于288dp的11个默认尺寸，恢复电源菜单和截图入口；不替换 SystemUI 主 APK | [截图菜单 overlay](docs/screenshot-menu-overlay.md) |
| `M19X6-Illumination-1.1.apk` | legacy camera1 照明通道，通知和快捷磁贴开关；用户确认修复，日志对应驱动 ENABLE/DISABLE | [照明使用与 Kotlin 构建](docs/illumination.md) |

```powershell
& $adb -s $serial install -r --no-incremental .\Camera2-M19X6-rear-preview180.apk
& $adb -s $serial install -r --no-incremental .\SystemUI-M19X6-small-width-overlay.apk
& $adb -s $serial shell cmd overlay enable --user 0 xusu616.vormor.systemui.smallwidth
& $adb -s $serial install -r --no-incremental .\M19X6-Illumination-1.1.apk
```

打开“词典笔照明”授予相机权限，再在快捷设置编辑页添加“照明”。开灯会占用 camera1，拍照前先关闭。overlay 没有桌面图标；通过 `cmd overlay list --user 0` 核对 `[x]`。若需要撤销，禁用 `xusu616.vormor.systemui.smallwidth` 即可，不清 SystemUI 数据。后续附件核对独立 Extras 校验清单，基础 `SHA256SUMS` 不会因此重新定义旧 ROM 文件。

### SystemUI 壁纸修正

Mali-400 的 EGL 1.4 驱动没有 `EGL_IMG_context_priority`，PHH Q SystemUI 却无条件要求这个属性，导致 EGL_BAD_ATTRIBUTE 和黑色壁纸。修正仅使 EglHelper 的属性数组在 `EGL_CONTEXT_CLIENT_VERSION, 2` 后结束；同一平台证书重新签名，其余非签名 APK 条目不变。脚本：`scripts/patch_wallpaper_egl.py`。

**SystemUI 是 persistent 应用，Android 10 拒绝 `adb install -r` 更新它。** 使用本次 ROM 已自动包含修正；若只修已有相同底包，在 TWRP 中替换 system 文件，不能按普通 App 安装。

```powershell
# 以下在匹配 TWRP、已挂载 system 后执行。
& $adb -s $serial pull /system/product/priv-app/SystemUI/SystemUI.apk .\SystemUI-before.apk
& $adb -s $serial push .\SystemUI-M19X6-EGL-compatible.apk /tmp/SystemUI-compatible.apk
& $adb -s $serial shell 'set -e; cp /tmp/SystemUI-compatible.apk /system/product/priv-app/SystemUI/SystemUI.apk.new; chown 0:0 /system/product/priv-app/SystemUI/SystemUI.apk.new; chmod 0644 /system/product/priv-app/SystemUI/SystemUI.apk.new; chcon u:object_r:system_file:s0 /system/product/priv-app/SystemUI/SystemUI.apk.new; mv /system/product/priv-app/SystemUI/SystemUI.apk.new /system/product/priv-app/SystemUI/SystemUI.apk; sync'
& $adb -s $serial shell sha256sum /system/product/priv-app/SystemUI/SystemUI.apk
```

期望 SHA `226c3de42b08069a7053abcb93a620c8d6c2510b43294407857e1053a1d3a4cb`。卸载 system，再正常重启；保留原 APK 和原壁纸数据。本机运行中替换后 remount-ro 曾返回 busy，故这里推荐 TWRP，不提供绕过 persistent 检查或清应用数据的方案。

## 从公开底包重建

脚本输入只有明确基底和配置，不需要 `.local-audit` 的中间镜像。它们在电脑工作，不连接设备。输出目录必须是新目录。所用 Windows magiskboot 来源于 [CYRUS-STUDIO/MagiskBootWindows](https://github.com/CYRUS-STUDIO/MagiskBootWindows) 的本地构建，SHA 为 `2d3f9dcdbf6fd9b8a5c8ab333c7434f43d8916ab29da81d6f9dc37f0731e8ea2`；其他工具需用参数明确它的哈希并通过解包比较。

```powershell
& $py .\scripts\build_port.py boot `
  --base-boot .\M19X6-Android81-Magisk30.6-base-boot.img `
  --magiskboot .\magiskboot-windows.exe --output-dir D:\a10-build-boot

& $py .\scripts\build_port.py system `
  --phh-system .\system-quack-arm-aonly-vanilla.img.xz `
  --systemui-apk .\SystemUI-M19X6-EGL-compatible.apk `
  --distro Ubuntu --output-dir D:\a10-build-system
```

boot 进行完整 CPIO、kernel、DTB 比对。system 可接受固定 xz/sparse/raw 三种输入，转 raw 后补三份原平台库、固定 VNDK27 引用、归档 split CIL、关闭 PHH 自动刷 system 入口、保持 ADB 授权并加入可选壁纸修正，最后验证内容、权限/标签和只读 fsck。编译 policy 的输入/参数在 `configs/provenance.json`；本次发布已包含匹配 policy v30。

工具版本、文件系统 inode 时间戳可能使重建镜像的整体 SHA 与已发布成品不同；每个输入/配置和关键内容仍校验。不能以一个不同整体 SHA 自动判断硬件兼容；需要完整 manifest 和启动测试。重建内核或移植到其他 vendor 不在这个 builder 的能力范围。

## BCB、回到系统与 mtkclient

本机有 `para`，并非没有启动控制区。旧 TWRP 清启动指令时查 `/misc`，本机只暴露 `/para`，所以 UI 点击“重启系统”可能继续回 TWRP。仅清 para 的 command[32]；禁止整分区清零，`+0x20000` 后还有 LK 环境。

在 TWRP 正常启动系统的受控入口：

```powershell
& $py .\scripts\flash_android10.py --adb $adb --serial $serial `
  --normal-boot --result-dir D:\a10-normal-boot-result
& $adb -s $serial reboot
```

若只能 BROM，使用原 mtkclient 入口等待/握手，不能把 `printgpt` 当成“进入 TWRP”命令。例子中的目录由本人填写：

```powershell
Set-Location "你的mtkclient目录"
& $py .\mtk ro 0x3d80000 0x200 D:\para-before.bin --parttype user
& $py "脚本目录\edit_bcb.py" --input D:\para-before.bin --output D:\para-recovery.bin --recovery
& $py .\mtk wo 0x3d80000 0x200 D:\para-recovery.bin --parttype user
& $py .\mtk ro 0x3d80000 0x200 D:\para-readback.bin --parttype user
```

读回必须与候选 512 字节逐字节相同，再按本人已验证的方法重启。legacy mtkclient 可能读满后仍打印 Failed，必须按真实文件长度和哈希判断；不要自动重试写入。mtkclient 的版本/驱动/USB DLL 属于本人电脑环境，未打包本机绝对路径脚本。

## Magisk-only 模块和照片 FAQ

在 Magisk 的模块页面选择从本地安装 M19X6-Magisk-only-su-v1.1.zip，安装后重启。模块停止 PHH sudaemon并把 /system/xbin/su 绑定到 /sbin/magisk。模块同时以 Magisk 标准挂载在同目录提供当前真实 magisk 二进制，满足 Magisk30.6的PATH命令布局检查。原 PHH 文件和应用数据保留；禁用或移除该模块再重启即可恢复 PHH。模块仅支持本项目 M19_X6/MT6580 和传统 /sbin Magisk布局。本机重启后PHH进程消失，标准su返回MAGISKSU；v1.1另补齐xbin/magisk真实入口，修正v1.0仍触发提示的布局缺口。


PHH Superuser 管理 PHH 的 Root 授权；Magisk 模块由 Magisk 加载。卸载 Superuser 的界面应用不等于停掉底层 daemon。Magisk 的“保留 dm-verity / AVB 2.0”控制校验标记，不会消除双 Root。完全卸载或直接安装可能修改启动文件；先保存当前适配 boot，再核对 APEX/helper/policy 等配置。本机一次 Magisk 30.6 直接重装只改变 `.backup/.magisk`，关键适配文件保留，但这不保证其他版本/配置同样如此。

通过 adb 复制图片后，相册可能暂时没有索引。先确认读存储权限和 `.nomedia`，再对具体文件扫描，不要清空 MediaProvider/相册数据：

```powershell
& $adb -s $serial shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///storage/emulated/0/Pictures/photo.png
```


隐藏 PHH Superuser 的桌面入口可以停用界面包，不卸载、不清数据：

```powershell
& $adb -s $serial shell pm disable-user --user 0 me.phh.superuser
# 要恢复入口时：
& $adb -s $serial shell pm enable --user 0 me.phh.superuser
```

若新 SD data 尚未安装 Magisk 管理器，Release 的 `Magisk-v30.6.apk` 为官方原包，SHA 已与官方资产 digest 核对：

```powershell
& $adb -s $serial install -r .\Magisk-v30.6.apk
```

boot 中的 Magisk 版本是30.6。若管理器要求补齐环境，应先保存当前适配boot并检查重打包后关键文件，不能把“取消保留启动校验”当成双Root修复。可选模块需完整Magisk环境；它不捆绑或清除管理器数据。

内置相机的最终独立补丁是 BACK-only `CaptureModule.updatePreviewTransform` 矩阵旋转，详见[相机说明](docs/camera-preview-experiment.md)。不要使用早期同时修改所有镜头 getPreviewOrientation 的试验包。截图和照明补充同样未写入基础 beta1 ROM，也不包含 SD 第三分区格式化或原 Apps2SD 数据迁移。

## Apps2SD 链接到 SD p3

本机已仅重新格式化旧 Apps2SD 的 p3，保留 p1 上当前 Android 10 的 data/cache 镜像和 p2。新 ext4 p3 由专用 Magisk 模块在 post-fs-data 阶段挂到 `/data/sdext2`；卡的 CID、容量、分区边界和新 UUID 必须匹配。生成的身份配置和模块仅保留本人私有，Release 提供生成脚本。

Apps2SD 16 的原 Magisk 接口使用旧路径，“普通方式”还会尝试接管 debuggerd。这里使用 `scripts/configure_apps2sd_external_mount.py` 登记已有外部挂载，并关闭 Apps2SD 自己的自动挂载和自动软重启。脚本操作应用内部的 `databases/apps2sd.db`；`/data/apps2sd/apps2sdpro.db` 只是会被重新导出的原生工具副本。

已通过独立测试包的 **APK 链接和正常重启**：原 APK 路径成为指向 p3 的符号链接，APK 校验值和内部测试文件内容保持一致，启动计数跨重启增加。Data、ODEX 和 lib 链接尚未验证，请先只选择 APK，不选择全选或系统／Root 工具。Apps2SD 的“操作前停用”选项会移除桌面图标，本次只在独立验证包上测试。

详细配置、实际菜单步骤、构建与验证范围见 [Apps2SD 说明](docs/apps2sd-external-mount.md)。已经按本机流程完成配置后，使用 Apps2SD 的“链接应用到 SD 卡 → 选择应用 → 链接/断开”，只勾选 APK 再完成。

## 来源和许可证

PHH 的公开镜像、Android/AOSP、Magisk、Chromium/WebView 和原厂平台库仍各自保留原许可证和权利归属。仓库 LICENSE 不重新授权第三方固件。原固件平台库及内核/DTB 仅用于固定 M19_X6 配置；没有确认可从头构建本机原内核的完整源码。APK 原始版本及重签/重建校验说明保留在配置与 Release 日志中。
