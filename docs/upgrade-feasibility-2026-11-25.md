# Android、WebView 和内核 Root 可行性：2026-11-25

结论：值得归档和研究，可以继续不刷机的分析；暂时没有已验证的本机新版系统/内核。先恢复可重建、可启动的设备内核，再讨论大幅升级或内核 Root。Magisk 是已在本机运行的路线。

## 已读取的设备事实

- VORMOR-X5pro，主板 M19_X6，MT6580，ARMv7，约 1 GiB RAM。
- Android 8.1.0 / API 27，Linux 3.18.79，内核编译标记 2023-09-15。
- `CONFIG_ANDROID_BINDER_IPC_32BIT=y`，Binder 设备为 binder、hwbinder、vndbinder。
- `ro.treble.enabled=true`，但 `ro.vndk.version` 为空、厂商 manifest 的 sepolicy 为 27.0、链接器 default namespace 未隔离。Treble 属性不足以证明现代 GSI 兼容。
- 当前 Magisk 30.6，SELinux 为 Permissive；`ro.boot.flash.locked=1`。Root 已可用不等于完成了 bootloader 解锁或验证了救砖路径。
- 当前 WebView provider 是 `com.google.android.webview`，版本 `138.0.7204.181`。这些是运行中的 provider 状态，不仅是 APK 文件名。

## 内核源码检索

本次以 VORMOR-X5pro、M19_X6、MT6580、3.18.79 及 M19 屏幕驱动名检索，没有找到可以确认对应这块主板的完整内核源码。这不是证明源码绝不存在。

找到两类素材：

1. [同型号 TWRP 设备树](https://github.com/ZH-XiJun/twrp_device_alps_VORMOR_X5_pro)，其 [BoardConfig.mk](https://github.com/ZH-XiJun/twrp_device_alps_VORMOR_X5_pro/blob/master/BoardConfig.mk) 强制使用 `prebuilt/kernel`，不是完整内核源码。文件里 `TARGET_KERNEL_SOURCE` 的字符串不能证明该目录真实发布了源码；其 Binder64 和 Android 16.1 等构建配置也不代表本机实际系统能力。
2. [SN4S/A_Plus_Oreo_Kernel_3.18.79](https://github.com/SN4S/A_Plus_Oreo_Kernel_3.18.79)：同芯片、同内核系列，但针对 Lenovo A1010a20。屏幕、触控和主板参数不同，只能用作移植基础。

本机内核配置列出的屏幕驱动为：`st7701s_wvga_m19_dsi_vdo`、`m19_jd9161z_wvga_dso_vdo_boe`、`st7701s_340x800_dsi_vdo_boe_3d51`。这些是编译进内核的候选驱动，不代表当前面板一定是其中哪一个。原机 DTB 和配置已保存，可辅助重建，但不等于 C 源码。

## 更高版本 Android

**不能直接套普通现代 GSI。** [AOSP 官方 GSI 文档](https://source.android.com/docs/core/tests/vts/gsi) 说明标准 Android 9 GSI 起使用 Binder64，Android 12 又移除了部分 Android 8.0/8.1 旧设备兼容措施。本机 Binder32、旧 VNDK、旧厂商 HAL、启动布局都需要具体适配，ARM CPU 位数和 Binder 协议位数要分别判断。

**Android 10 定制路线有源码依据，但没有本机验证。** [LineageOS 17.1 的 libbinder](https://github.com/LineageOS/android_frameworks_native/blob/lineage-17.1/libs/binder/Android.bp) 和 [libhwbinder](https://github.com/LineageOS/android_system_libhwbinder/blob/lineage-17.1/Android.bp) 仍保留 Binder32 构建配置。可以将定制 ARM32/Binder32 的 Android 10 作为第一阶段研究目标；必须解决厂商库依赖、图形、触屏、音频、Wi-Fi、相机等，不能称为已完成的 ROM。Android 11 或更高版本需要另行评估，不能保证。

另一条路线是重建支持 Binder64 的设备内核，并让 HAL/用户空间匹配。不能只换内核的一项配置而忽略原厂 Binder32 用户空间。

内核 3.18 不意味着所有更高 Android 都绝对不能运行，但不能把其他芯片或设备的成功实例当成本机可启动证据。直接换到主线 Linux 5/6 也需要移植 MediaTek 和外设驱动，远超修改版本号。

## 更高版本 WebView

[Chromium 官方公告（2025-06-18）](https://groups.google.com/a/chromium.org/g/chromium-dev/c/vEZz0721rUY/m/pUIgqXxNBQAJ) 确认 138 是 Android 8/9 的最后支持代际，139 起最低 Android 10 / API 29。当前 [WebView 开发设备要求](https://chromium.googlesource.com/chromium/src/+/main/android_webview/docs/device-setup.md) 也要求 API 29 及以上。

当前安装的 `138.0.7204.181` 已属于 Android 8.1 的最后支持代际，本次没有将它声称为 138 分支的最后一个补丁版本。升级到 Android 9 不能突破该上限。

[已有 AnyWebView](https://github.com/neoblackxt/AnyWebView) 改变 provider 选择机制，不能补齐新版 Chromium 所依赖的系统 Java/native API。仅修改 APK 的 minSdk 或升级 Linux 内核都不足以让官方新 WebView 在 Android 8.1 上兼容。

若先移植出可用的 Android 10+，再选择仍支持 ARM32 的相应 WebView，这是更合理的研究顺序。若坚持 Android 8.1，则需回移新版 Chromium 的兼容改动并维护构建，属于长期分叉，现阶段没有本机可用产物。

## KernelSU Next、non-GKI 和 KPM

你提到的 `nongki` 很可能是 `non-GKI`，意为非通用内核镜像设备，不是可以嵌入的独立组件；`pkm` 很可能是 `KPM`。

[KernelSU Next 官方](https://github.com/KernelSU-Next/KernelSU-Next) 列出的架构为 ARM64 和 x86_64，3.18+ 仅实验性并可能需要回移。即使内核版本能处理，本机 ARMv7 仍不在官方列出的架构中。若研究 ARM32 分支或自行移植，需要核实内核驱动与管理器/ksud 的架构支持。

[non-GKI 集成指南](https://kernelsu-next.github.io/webpage/pages/how-to-integrate-for-non-gki.html) 的前提是先能从源码编译出可启动内核，再加入驱动和 hooks。本机 `CONFIG_KPROBES` 未开启，必须在源码层处理 hooks/回移，不能在普通 Magisk 模块中凭空获得该能力。

若你真正想说的是 SUSFS，它是另一套内核隐藏扩展；需要单独适配内核和对应 Root 框架，也没有确认本机 3.18 ARM32 的现成可刷方案。

[KPatch-Next](https://github.com/KernelSU-Next/KPatch-Next) 明确仅支持 ARM64，虽然声明 Linux 3.18–6.12 的理论范围，本机 ARMv7 仍不可直接使用。因此不安装现成 KPatch/KPM ZIP。已运行的 Magisk 更现实，是否隐藏有效取决于具体检测项，不能保证所有应用都通过。

## 后续顺序

1. 保留当前可启动状态，补齐用于恢复的 system/vendor、bootloader 和分区信息；现有散包不是整机救砖包。
2. 明确 M19 主板外设驱动和源码来源；先做到原有 8.1 内核可重建、可启动。
3. 以 Android 10 的 ARM32/Binder 兼容移植为阶段目标，验证真实硬件功能。
4. 系统可用后再评估 WebView 与 Root；KernelSU Next/内核隐藏属于额外的 ARM32 移植工作。

当前分析、校验、打包和源码检索不需要你在机器旁。首次切换启动镜像、重建内核启动测试、解锁、进入 BROM/恢复模式或更换系统时，需要你能接触设备，因为失败后 ADB 可能消失，要用按键、数据线或主板救砖入口恢复。本次没有刷写或重启。
