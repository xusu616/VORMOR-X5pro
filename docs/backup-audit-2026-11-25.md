# 备份核对：2026-11-25

核对目录：`F:\ROMbackUp\VORMOR-X5pro`。通过已授权的 rooted ADB 读取设备 `/dev/block` 分区，没有重启、擦除、解锁或刷写。采用整个分区 SHA-256；短于分区的 TWRP 另做同长度前缀及尾部检查。

| 本地文件 | 设备来源 | 结果 |
| --- | --- | --- |
| `boot0.img`，4 MiB | `/dev/block/mmcblk0boot0` | 完全一致 |
| `boot1.img`，4 MiB | `/dev/block/mmcblk0boot1` | 完全一致 |
| `nvram.img`，5 MiB（本地私有） | `/dev/block/mmcblk0p2` | 完全一致 |
| `boot.img`，16 MiB | `/dev/block/mmcblk0p8` | 整体不同；内核、DTB 相同，ramdisk 不同 |
| `recovery.img`，16 MiB | `/dev/block/mmcblk0p9` | 不同，设备已换为 TWRP |
| `twrp.img`，10,399,744 字节 | 当前 recovery 前 10,399,744 字节 | 完全一致；分区剩余字节全部为零 |
| `Unofficial/twrp.img` | 同上 | 与根目录 TWRP 完全一致 |

旧 boot 与当前 boot 的 ramdisk 都含 Magisk 备份和注入文件。因此旧 `boot.img` 并非未经修改的原厂启动镜像。当前运行 Magisk 30.6；两份 ramdisk 的打包与 Magisk 内容不同，本次没有识别旧 Magisk 的精确版本。

Boot 的解包后内核 SHA-256：`afd1b9ad1fb6a27eb319944397f9b2de2eb87c809942701527e44674338dd3c9`。

Boot 的 DTB SHA-256：`210da8721c5f9869cf6387b9bb91fa9e610f6fd32d10b41b67eb144905229630`。

当前完整 boot SHA-256：`8aee6807955c700946a031837266ba0364c549b6a150374cac4fab924d21c35b`。

当前完整 recovery SHA-256：`98ac5051b00c5f8194973dad4f23ae11119899a7c99a2cfc037718030331a4ee`。

当前 boot、recovery、`config.gz`、解压后的 `kernel.config`、厂商 manifest 和全部核对哈希已保存于本地 `.local-audit/2026-11-25/`。这些当前状态文件未公开提交，原有备份文件未覆盖。

## 恢复能力的边界

现有备份没有 `system`、`vendor`、`lk/lk2`、完整 GPT/eMMC 等，不能作为整机救砖包。`MT6580_Android_scatter.txt` 只有 PRELOADER 一项，其引用的 `preloader.bin` 也不存在，不能直接据此进行完整线刷。`boot0/boot1` 是 4 MiB eMMC boot 区备份，不可自动当成任意 scatter 中要求的裸 preloader 文件。

NVRAM 与固件应分别保存。NVRAM 可能包含本机标识及射频校准；本地副本保留，从当前 Git 跟踪中移除，旧历史中的副本仍存在。本次没有改写历史。
