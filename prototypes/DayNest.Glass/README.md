# WinUI 玻璃日历实验

构建：`dotnet build prototypes/DayNest.Glass/DayNest.Glass.csproj -c Debug -p:Platform=x64`

运行：`prototypes/DayNest.Glass/bin/x64/Debug/net10.0-windows10.0.26100.0/win-x64/DayNest.Glass.exe`

需要 Windows 11、.NET 10、仓库 `.venv` 中的 Python 依赖。
读取原版 DayNest 的账户和加密缓存；打开时只读取缓存，选择日期后点击“刷新本月”读取该日期所在月份的真实日历。同步结果暂存在新界面内存中，不修改原版缓存。密码在 Python 中解密，不传入进程命令行或 WinUI 界面。

当前包括原生 Acrylic、深浅主题、月历、日期选择、单日安排及完整备注。新增/编辑、固定项管理、桌面层级与账户设置尚未迁移，继续使用原版程序。日历内置箭头只翻页，选中日期后才决定刷新月份。未接入 Pane 的自定义材质、双层阴影。此版本不是原版功能的完整替代。

## 分层材质试验（GlassFinal）

本次参考 Pane 的染色/亮度分离与边缘高光设计，使用独立实现的 WinUI `DesktopAcrylicController` 调整材质；没有复制 Pane 的双 HWND 宿主或 C++ 效果代码。参考源码：https://github.com/LBEILC/Pane/blob/cfa1951069ea2656f582c7aee092783610c63e05/src/Pane.App/Hosting/SceneB.cs

移除原来 67%–73% 不透明的页面遮罩，改为较薄渐变染色；“玻璃浓度”同时调整系统材质染色与页面染色，范围 15%–80%，默认 42%。主题、浓度仅在本次进程内生效。系统未开启透明效果、节能或窗口失焦时，系统可能使用不透明回退材质。未实现 Pane 的双层阴影与饱和度效果。

构建：`dotnet build prototypes/DayNest.Glass/DayNest.Glass.csproj -c Debug -p:Platform=x64 -p:OutputPath=bin/GlassFinal/`

启动：`prototypes/DayNest.Glass/bin/GlassFinal/DayNest.Glass.exe`

稳定性修复：自定义玻璃控制器独立持有 SystemBackdropConfiguration，由窗口显式提供激活与主题状态。避免系统默认配置变化回调中 target 无效导致的 0x80070057 异常。保留应用强引用。可用 --render-stress 执行 60 轮移动/缩放/主题/材质与强制 GC 检查，结果写入 EXE 目录 render-stress.txt；未处理的 WinUI 异常写入 render-errors.log。
