# VORMOR-X5pro 固件资料

贝铂 X5pro / VORMOR-X5pro，主板 `M19_X6`，MT6580，32 位 ARM，Android 8.1.0，Linux 3.18.79。

该仓库用于保存已有启动镜像、第三方 TWRP、WebView APK 和设备研究资料。它不是完整原厂 ROM，也没有确认的本机可构建内核源码。

- [2026-11-25 备份核对结果](docs/backup-audit-2026-11-25.md)
- [Android、WebView 和内核 Root 可行性](docs/upgrade-feasibility-2026-11-25.md)
- [基带固件来源及校验](firmware/README.md)

`boot.img` 已含旧版 Magisk 修改；当前设备 boot 使用相同内核/DTB、不同 Magisk ramdisk。`recovery.img` 是旧备份；当前 recovery 对应 `twrp.img` 补零到 16 MiB 后的内容。不能将这些镜像全部称作原厂未修改备份。

2026-11-25 的当前 boot、recovery、内核配置及完整本机审计保存在 `.local-audit/2026-11-25/`，已排除 Git 提交。

`nvram.img` 保留在本地，已从当前 Git 跟踪目录移除。历史提交仍包含它；本次未改写或强推历史。以后不要公开个人校准、账号、安全密钥或用户数据。

根目录 LICENSE 不改变第三方固件、Android/WebView 和 TWRP 的原有许可证或权利归属，具体来源见对应说明。
