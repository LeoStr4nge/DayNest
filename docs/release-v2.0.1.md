# DayNest 2.0.1 · 界面体验与加载优化

Windows 11 x64 的 WinUI 3 桌面日历便携版。完整解压 `DayNest-2.0.1-WinUI-Portable-win-x64.zip`，运行 `DayNest/DayNest.Glass.exe`；包内已包含 .NET、Windows App SDK 和 Python 后端。

## 本版改进

- “今日／近期／本月”改为圆形指示器滑动的长条导航，当前视图更清晰。
- 修复导航按钮悬停和切换后的闪烁，移除卡片及主界面按钮的整体缩放，让文字保持稳定。
- 刷新期间显示进度环，完成或取消后恢复按钮。
- 今日与近期视图按需加载月份；按日期建立日程索引，减少重复扫描和不必要的相邻月份预加载。

## 使用与兼容

需要 Windows 11 x64（build 22000 或更新）。默认使用桌面小组件模式；如果找不到窗口，运行 `DayNest.Glass.exe --normal-window` 可切换到普通窗口。更新前请退出旧版本，再完整解压新包。账户和加密日程缓存沿用 `%APPDATA%\DayNest`，外观与位置沿用 `%LOCALAPPDATA%\DayNest`。

本版仍是便携包，没有安装向导或代码签名。重复／全天日程编辑、跨日历移动等现有限制未变。源代码遵循 GPL-3.0-only，第三方许可证随包附带；可使用 `SHA256SUMS.txt` 核验压缩包。
