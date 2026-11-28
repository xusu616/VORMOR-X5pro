# Apps2SD 使用独立 p3 挂载

这个流程只适用于本项目 Android 10 的隔离 `/data`，Apps2SD 16（versionCode 160）及已经核对身份的新 ext4 p3。它没有把原 Apps2SD 分区的数据迁移到新文件系统。格式化 p3 是独立操作，必须先取得对该分区数据损失的明确授权；这里的脚本不会格式化。

## 单一挂载所有者

`scripts/build_apps2sd_mount_module.py` 在电脑上生成专用 Magisk 模块。每张卡必须使用本人 SD 的 CID、容量、p3 起点／长度和新 UUID。启动时全部一致才只对 p3 执行 `blockdev --setrw`，然后在同步 post-fs-data 阶段挂载 `/data/sdext2`。它不解除原 userdata、NVRAM 或其他分区的只读。

UUID 不匹配或已有其他挂载时立即停止，不重试。自己的 mount 失败时，能安全卸载就恢复 p3 块只读。日志在该模块目录的 `mount.log`；`sys.apps2sd.mount_state` 只有验证挂载并给新根 inode 设置 SELinux 标签后才为 `ready`。

Magisk 的全局 `post-fs-data.d` 早于模块脚本；Apps2SD 不应同时生成启动挂载脚本。Magisk 的 40 秒启动阻塞窗口也意味着，慢卡／故障卡不能仅凭模块保证必需应用的链接一直可见。若要链接关键系统应用，需要独立 init 门控；本次先用隔离的测试 APK 验证，不迁移用户常用应用。

```powershell
python .\scripts\build_apps2sd_mount_module.py `
  --sd-cid "本人SD的32位十六进制CID" `
  --p3-start-sector 你的起始sector --p3-sectors 你的长度sector `
  --sd-sectors 你的整卡长度sector --filesystem-uuid "格式化之后的新UUID" `
  --output-dir D:\apps2sd-private-module
```

生成的模块包含本人 SD 身份，应仅保留私有，不随通用 Release 上传。模块禁用或移除并重启后，不再由它解除 p3 只读或挂载。

## 旧 Apps2SD 的“普通方式”陷阱

此 APK 的“Use normal method”不是“已由外部挂载”的模式。未选择 init.d／su.d／高级方式时，它仍进入 Create Mount Script，并可能构造 `/system/bin/debuggerd` 包装入口，运行 `/system/etc/apps2sd-mountscript.sh` 后再执行 `debuggerd.bin`。它的 Magisk 分支也只识别旧 `/sbin/.core/img/.core/post-fs-data.d`。

因此不要为了登记 ext4 而在这个创建脚本对话框里点击完成。外部专用模块负责挂载，Apps2SD 只负责用户明确选择的链接操作。

`scripts/configure_apps2sd_external_mount.py` 默认只读计划；明确 `--configure` 才停止 Apps2SD、用 SQLite `.backup` 保存数据库并验证完整性、备份偏好设置，然后只在空的 `filesystem` 表添加一条 p3／ext4 元数据。已有不同元数据立即停止，不覆盖。偏好只改 `disable_auto_mount=true` 和 `auto_soft_reboot=false`，因为仅禁用自动挂载、却仍启用自动软重启，会继续进入其挂载分支。

配置必须写入应用拥有的 `/data/data/in.co.pricealert.apps2sd/databases/apps2sd.db`：APK 的 `aes` 类把 `apps2sd.db` 交给 `SQLiteOpenHelper`。`/data/apps2sd/apps2sdpro.db` 是给 native 工具使用的导出副本，应用下一次运行会覆盖它。此前只改导出副本时，APK 链接仍在，但 `filesystem` 行丢失并再次弹出创建脚本对话框。配置脚本已改为原生应用数据库，并增加回归检查，避免再次写错状态所有者。

```powershell
# 已有 root ADB；脚本不会自动启用 Root、挂载或重启。
python .\scripts\configure_apps2sd_external_mount.py --adb adb `
  --serial "本人ADB序列号" --result-dir D:\apps2sd-private-plan

python .\scripts\configure_apps2sd_external_mount.py --adb adb `
  --serial "本人ADB序列号" --result-dir D:\apps2sd-private-config --configure
```

这个脚本只支持核对过的 versionCode 160 与精确表结构。p3 必须已在 PID1 的命名空间中 rw 挂载，且专用模块状态为 ready。数据库和 XML 备份仅保留私有。XML 替换使用同目录原子 rename，并由 `magisk --clone-attr` 保留原权限、owner 与 SELinux 标签。它不清数据、不卸载应用，也不创建旧挂载脚本。

分区登记已在本机通过正常重启验证：应用内部的 `filesystem` 记录保留，配置助手再次只读检查时不再需要添加记录。不要编辑给原生工具导出的数据库副本来替代此配置。

## 单独验证链接

测试包为 `xusu616.vormor.apps2sdprobe`，与用户应用完全隔离。源码在 `apps/apps2sd-link-probe/`，`scripts/build_apps2sd_probe.py` 使用显式 Kotlin／SDK／签名工具参数构建，不升级 Gradle。

应用只保存自己的启动计数和 `apps2sd-probe.txt`。**目前只验证 APK 链接**：在 Apps2SD 中仅勾选这个测试包的 APK，不勾选 ODEX、lib 或 Data，保留用户常用应用及其存储。测试文件和计数继续留在内部隔离 data；APK 的符号链接应指向 p3。

本机实际测试中，APK 从 `/data/app/.../base.apk` 链接到 `/data/sdext2/apk/.../base.apk`，APK 哈希保持不变，应用 installed/enabled 为 true；正常重启后计数从 1→2→3，内部测试文件哈希保持不变，p3 在 package 服务出现前已 ready。这证明本次 APK 链接与重启路径通过，不证明 Data／ODEX／lib 已适配。

Apps2SD 在链接后可能仍保存 `/system/etc/apps2sd-mountscript.sh`、`00000000apps2sd-main.sh` 及 `/data/apps2sd/apps2sd-mountscript-2.sh` 等模板。模板文件存在和注册了启动入口是两件事；本次没有注册另一个 post-fs-data/service.d 脚本，`debuggerd` 与 `vold` 保留原 ELF，system 在重启后为只读。不要宣称整个链接过程没有创建模板。

`save_script_system_partition` 在这个 APK 中默认是 false，作用是让 OBB、外部数据和文件夹 bind 模板保存在 data 而不是 system；它不是“禁止所有 system 写入”的选项，不能阻止主挂载模板生成。独立配置助手不擅自更改第三个偏好，也不依赖这个选项来保证没有旧式启动入口。

离线代码确认普通内部 Data 选项使用符号链接：DATA 项进入 link 路径，最终调用 `ln -sf`；OBB、外部数据及文件夹则有独立 bind 路径。内部 Data 的符号链接不需要每次重建 bind，但 Android 10 的目录 inode、权限、SELinux 标签、设备保护数据目录等仍需实际验证。禁用自动挂载不等于已经验证所有 Data 链接，因此当前仍只推荐非关键测试 APK 的 APK 链接。
