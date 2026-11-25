# MT6580 基带固件归档

2026-11-25 从当前 VORMOR-X5pro / M19_X6 的 `/vendor/firmware` 只读提取，并与设备文件完整 SHA-256 核对。没有刷写设备。

| 文件 | 大小 | 用途 |
| --- | ---: | --- |
| `modem_1_wg_n.img` | 5,057,036 字节 | 厂商 modem 固件 |
| `catcher_filter_1_wg_n.bin` | 1,472 字节 | 与该固件配套的 Catcher 过滤配置 |

固件可见版本字符串为 `MOLY.WR8.W1449.MD.WG.MP.V251.4.T1`，平台字符串为 `MT6580_S00`。完整来源和哈希见 [manifest.json](manifest.json)，文件校验表见 [SHA256SUMS](SHA256SUMS)。

本机分区表没有独立 `modem` 分区，这两个文件原本位于 vendor 文件系统内。不要将它们作为整分区镜像刷入 boot、recovery、vendor 或 NVRAM。固件存在不代表这块主板装有可用的蜂窝射频硬件；本次设备的 `gsm.version.baseband` 属性为空，尚未验证蜂窝通信。

`nvram.img` 是单机校准/恢复数据，不是通用 modem 固件。它仅保留本地，不随本次归档发布。

这些文件是厂商第三方二进制，不能因为根目录有 MIT LICENSE 就将它们标为 MIT 开源。没有取得或确认其再分发许可；原有权利仍属于原权利人。
