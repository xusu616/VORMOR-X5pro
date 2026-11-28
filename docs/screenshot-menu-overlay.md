# 小宽度屏幕的电源菜单／截图入口

`SystemUI-M19X6-small-width-overlay.apk` 是针对 PHH v222 SystemUI 的资源覆盖包，未加入基础 beta1 ROM。它与 ROM 内已经包含的 `SystemUI-M19X6-EGL-compatible.apk` 壁纸补丁是两个独立修正。

本机显示为 340×800、200 dpi，逻辑宽度约272dp。PHH v222 的电源菜单 grid 有11个尺寸只定义了 `sw288dp` 及更宽屏幕值，缺少默认值。打开电源菜单时 `global_actions_column.xml:39` 的 paddingLeft 无法解析为尺寸，SystemUI 崩溃，framework 随后显示不含截图的 Legacy 菜单。截图入口并未从 APK 删除。

本覆盖包只为这11个尺寸提供原有 `sw288dp` 基线：64dp按钮、20dp图标和对应边距，不改全局分辨率／density、不改 framework ID、不添加异常兜底。覆盖启用后已观察到正常电源菜单和“屏幕截图”入口。

## 安装、启用与恢复

包名 `xusu616.vormor.systemui.smallwidth`，无应用代码和桌面 Activity；签名与本 SystemUI 的平台证书匹配。APK SHA-256：`c554f09b7cb271c398207327997dd53159ae65f769e7f4c7c77f959f4368b802`。

```powershell
$adb = "adb"
$serial = "你自己的ADB序列号"
& $adb -s $serial install -r --no-incremental .\SystemUI-M19X6-small-width-overlay.apk
& $adb -s $serial shell cmd overlay enable --user 0 xusu616.vormor.systemui.smallwidth
& $adb -s $serial shell cmd overlay list --user 0
```

确认列表中该包为 `[x]`，再长按电源打开菜单。若需要恢复覆盖前状态，禁用即可，不清 SystemUI 数据：

```powershell
& $adb -s $serial shell cmd overlay disable --user 0 xusu616.vormor.systemui.smallwidth
```

其他 ROM 的平台签名或 overlay 权限可能不同；安装成功也不代表资源覆盖已获准。截图快捷键是电源＋音量下；Q 默认两键按下相隔不超过150ms并保持约500ms。Q 原生快捷设置没有独立截图磁贴。截图仍需自行确认保存成功；`adb exec-out screencap -p` 不经过同一 SystemUI 入口，不能单独替代该验证。

## 从资源源文件构建

输入在 `overlays/systemui-small-width/`：`AndroidManifest.xml` 声明只覆盖 `com.android.systemui`，`res/values/dimens.xml` 提供11项默认值。准备 Java 和 Android SDK build-tools，并使用与本 SystemUI 一致的公开 AOSP platform key 签名；不要把 testkey 与 platform key 混用。

```powershell
$buildTools = "C:\Android\Sdk\build-tools\36.0.0"
$androidJar = "C:\Android\Sdk\platforms\android-29\android.jar"
New-Item -ItemType Directory D:\systemui-overlay-build
& "$buildTools\aapt2.exe" compile --dir .\overlays\systemui-small-width\res `
  -o D:\systemui-overlay-build\resources.zip
& "$buildTools\aapt2.exe" link -I $androidJar `
  --manifest .\overlays\systemui-small-width\AndroidManifest.xml `
  --auto-add-overlay -o D:\systemui-overlay-build\unsigned.apk `
  D:\systemui-overlay-build\resources.zip
& "$buildTools\zipalign.exe" -p 4 D:\systemui-overlay-build\unsigned.apk D:\systemui-overlay-build\aligned.apk
& "$buildTools\apksigner.bat" sign --key .\platform.pk8 --cert .\platform.x509.pem `
  --v1-signing-enabled true --v2-signing-enabled true `
  --out D:\systemui-overlay-build\SystemUI-M19X6-small-width-overlay.apk D:\systemui-overlay-build\aligned.apk
& "$buildTools\apksigner.bat" verify --min-sdk-version 29 --print-certs `
  D:\systemui-overlay-build\SystemUI-M19X6-small-width-overlay.apk
```

匹配的平台证书 SHA-256 是 `c8a2e9bccf597c2fb6dc66bee293fc13f2fc47ec77bc6b2b0d52c11f51192ab8`。构建后用 `aapt2 dump resources` 确认仅预期11项 dimen，并在设备核对 overlay 状态、菜单无新 InflateException 和截图结果。
