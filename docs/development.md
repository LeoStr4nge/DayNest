# DayNest 开发手册

## 当前架构

主界面仅使用 C# / WinUI 3。旧 Python/Tk 窗口、启动器、主题与窗口效果代码，以及专用 PyInstaller / Inno Setup 安装流程已退役；历史代码可通过 Git 历史或 v2.0.0 标签查阅。

Python 并未退役：WinUI 通过独立桥接进程调用其 CalDAV、DPAPI、iCalendar 和缓存逻辑。`daynest.py` 是后端模块，不再提供直接启动的图形界面。

| 路径 | 职责 |
| --- | --- |
| `prototypes/DayNest.Glass/*.cs`、`App.xaml` | 当前 WinUI 界面、材质、桌面模式、单实例及设置 |
| `prototypes/DayNest.Glass/calendar_bridge.py` | JSON 桥接入口，账户、同步、日程与固定项操作 |
| `daynest.py` | CalDAV、事件解析、增量资源缓存、DPAPI 与原子存储 |
| `tools/build_glass_release.py` | 当前自带运行环境的 WinUI 便携包构建 |
| `tools/generate_icon.py`、`assets/` | 图标生成与图标资源 |
| `tests/` | Python 后端离线回归检查及统一运行器 |
| `prototypes/DayNest.Glass/check_*.py` | 桥接离线检查和需要 EXE 的界面检查 |

源码目录暂保留 `prototypes` 名称以避免破坏构建路径。外观文件仍叫 `glass-preview.json`，沿用已有用户配置，不因目录或文件名带有旧称而删除。

## 开发环境与启动

需要 Windows 11 x64、.NET 10 SDK、Visual Studio 的 WinUI 构建工具及 Python 3.11 或以上。仓库使用 `.venv`；经验证的当前构建环境为 Python 3.13。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
dotnet build prototypes/DayNest.Glass/DayNest.Glass.csproj -c Debug -p:Platform=x64 -p:OutputPath=bin/GlassFinal/
.\prototypes\DayNest.Glass\bin\GlassFinal\DayNest.Glass.exe
```

构建前关闭同一输出目录中的运行实例。恢复普通窗口可给 EXE 添加 `--normal-window`。开发版从仓库寻找 Python 和桥接脚本；便携发布版调用包内 `backend/DayNest.Bridge.exe`。

为截图或展示使用 `DayNest.Glass.exe --demo`：单独打开桌面小组件，使用内存中的虚构日程与倒计时，不读取真实账户、缓存或外观配置，不访问日历服务器，也不保存演示设置或窗口位置。可附加 `--i18n-check` 或 `--i18n-check-ja` 预览英语或日语界面，附加 `--normal-window` 可临时切换为普通窗口。演示窗口需由使用者自行关闭。

## 数据与并发

账户、加密日程和日志仍在 `%APPDATA%\DayNest` 的 `config.json`、`cache.dat` 和 `sync.log`，外观与位置在 `%LOCALAPPDATA%\DayNest`。保留旧配置未知字段，沿用账户/缓存格式；删除旧 UI 代码不迁移或删除用户数据。

WinUI 使用独立的应用单实例锁和命名管道唤回。Python 桥接进程通过保留名称的 `Local\DayNest.SingleInstance` 锁串行化同步和写入，兼容旧版本进程的访问保护。不要因其旧名称而移除。账户切换使旧缓存和操作令牌失效；缓存采用 DPAPI 加密及原子替换。

网络读取使用 ETag 与资源缓存；完整月份才落盘，持久月份保留当前月前后各六个月。写入使用条件请求，不自动重试或跟随重定向，避免重复新增和覆盖并发修改。日程详情、固定项跟踪和同步的详细行为见 [WinUI 说明](../prototypes/DayNest.Glass/README.md)。

## 验证

```powershell
.\.venv\Scripts\python.exe -B tests/run_checks.py
.\prototypes\DayNest.Glass\bin\GlassFinal\DayNest.Glass.exe --self-test
.\prototypes\DayNest.Glass\bin\GlassFinal\DayNest.Glass.exe --calendar-flow-check --normal-window
```

统一 Python 运行器涵盖后端和五组桥接检查，使用模拟服务器或临时文件，不访问真实日历。WinUI 另有材质压力、桌面、功能和单实例检查，命令见 WinUI 说明。测试结束关闭所有测试窗口；不要用测试账户覆盖真实配置，或向真实日历写入测试日程。

## 发布

先安装 `requirements-build.txt`，再运行 `tools/build_glass_release.py`，传入版本号、Visual Studio x64 CRT 目录和 CRT 许可目录，具体命令见 WinUI 说明。脚本发布自带运行时的前端并冻结 Python 后端；后端不再依赖或打包 Tk/Tcl。附带 GPL、Python、dateutil、six、PyInstaller、.NET、Windows App SDK 和 VC++ 运行库许可。

`build/`、`dist/`、`release/`、`.venv/` 及 WinUI 的 `bin/`、`obj/` 均为忽略的本机产物，不属于源码。历史发布说明 [v2.0.0](release-v2.0.0.md) 记录发布当时的内容，已发布标签和压缩包不随主分支清理而改写。
