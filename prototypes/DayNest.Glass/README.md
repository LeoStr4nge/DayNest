# DayNest WinUI 玻璃日历实验

此分支用于验证 Windows 11 上的 WinUI 3 界面；原版 Python/Tk 程序仍为功能完整的版本。新界面用 C# 编写，CalDAV、DPAPI 账户读取及日程解析复用 Python；目前没有 C++ 代码。

## 构建与启动

需要 Windows 11、.NET 10 SDK、WinUI 构建工具，以及仓库 `.venv` 中已安装 `requirements.txt` 的 Python 环境。

```powershell
dotnet build prototypes/DayNest.Glass/DayNest.Glass.csproj -c Debug -p:Platform=x64 -p:OutputPath=bin/GlassFinal/
.\prototypes\DayNest.Glass\bin\GlassFinal\DayNest.Glass.exe
```

重新编译前先关闭该输出目录下运行的窗口。

## 当前功能

- 自定义日期网格、翻月、今天、单日安排与完整备注。
- 从原版加密缓存读取真实日程，手动刷新所选月份；新同步结果只保存在原型内存中。
- 日期下方显示日程标记，按跨天持续时间计算，午夜结束不标记下一天。
- 顶部显示原版已保存的固定倒计时。这是只读缓存快照，外部改期/删除跟踪及固定项管理仍由原版负责。
- 深浅主题、玻璃浓度自动保存到 `%LOCALAPPDATA%\DayNest\glass-preview.json`，不改动原版配置。写入失败时界面提示；无效配置恢复默认。
- 切换月份会取消旧的读取进程；关闭窗口取消读取任务。

首次无账户时，请在原版配置。Python 内解密密码，不将凭据传给 WinUI 或进程命令行。原型不写入原版日程缓存或账户。

## 材质与稳定性

参考 [Pane 的 SceneB](https://github.com/LBEILC/Pane/blob/cfa1951069ea2656f582c7aee092783610c63e05/src/Pane.App/Hosting/SceneB.cs) 的染色/亮度分离与边缘高光设计，独立实现 `DesktopAcrylicController`。未复制 Pane 的双 HWND 宿主或 C++ 效果代码；双层阴影与饱和度效果尚未实现。

浓度范围 15%–80%，默认 42%。薄渐变染色保护文字对比度；系统根据透明效果、节能或失焦状态可能启用不透明回退。

自定义控制器持有独立的 `SystemBackdropConfiguration`，显式更新主题及激活状态，避免查询默认配置时 target 无效引起的 0x80070057 闪退。应用保留强引用。

## 验证

```powershell
.\.venv\Scripts\python.exe -B prototypes/DayNest.Glass/check_bridge.py
.\prototypes\DayNest.Glass\bin\GlassFinal\DayNest.Glass.exe --self-test
.\prototypes\DayNest.Glass\bin\GlassFinal\DayNest.Glass.exe --render-stress
```

`--self-test` 不打开窗口，检查独立临时目录中的外观保存/恢复，以及跨天、午夜和零时长日程日期，报告写入 EXE 目录 `self-test.txt`。

`--render-stress` 打开窗口，执行 60 轮移动、缩放、主题/浓度调整和强制 GC；不保存外观，结果写入 `render-stress.txt`。未处理 WinUI 异常写入 `render-errors.log`。桥接检查模拟配置和缓存，不访问真实服务器。

## 合并条件

当前保留实验分支，不合并 main。合并前需要完成或明确规划：日程新增/编辑、账户设置、固定项管理、桌面层级和单实例、发布打包、真实日历同步回归、多屏/DPI 与长期驻留稳定性验证。当前检查不能替代上述验收。
