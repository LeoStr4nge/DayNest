# DayNest 开发手册

## 项目概况

DayNest 1.0.0 是面向 Windows 的中文桌面日历小组件。项目以通用 CalDAV 日历组件为方向，界面统一使用“日历账户”“账户名或邮箱”和“日历密码”等称呼。连接配置提供 iCloud 预设和自定义 HTTPS CalDAV 两种选择，发现、读取、固定项跟踪和写入共享当前配置。iCloud 保留已知服务域名规则，自定义服务按明确配置的可信来源校验。历史版本曾完成 iCloud 的实际服务测试；本次多服务改造仅通过离线模拟检查，尚未经过真实服务器测试，包括 iCloud 预设回归和自定义服务。

已验证的环境为 Python 3.11、Tkinter 和 python-dateutil 2.9.0.post0。

## 代码结构

```text
DayNest.pyw             图形启动入口
daynest.py              主程序、同步、缓存和界面
RestoreWindow.pyw       关闭桌面模式并重新启动
requirements.txt        Python 依赖
requirements-build.txt  打包和图标生成依赖
assets/                 程序图标与源图形
packaging/              PyInstaller、Inno Setup 配置及许可补充文件
tools/                  发布构建、图标生成和安装检查
tests/check_*.py        离线检查脚本
tests/run_checks.py     检查运行器
```

主程序中的主要职责：

- `CalDAV`：账户发现、资源列表、批量下载和条件写入。
- `ResourceCache`：资源正文与 ETag 缓存、并发下载协调及持久化快照。
- iCalendar 辅助函数：事件字段、备注、时区、持续时长与重复规则。
- `App`：Tk 界面、后台任务、状态与存储管理。
- `SlimScrollbar`：深色滚动条和滚动交互。

## 应用身份与数据

应用名为 `DayNest`，首发版本号为 `1.0.0`。代码只使用以下目录，不读取其他应用目录：

```text
%APPDATA%\DayNest\
  config.json      配置；日历密码为 DPAPI 加密文本，账户名或邮箱未加密
  cache.dat        DPAPI 加密的日程、月份、固定项和资源缓存
  sync.log         同步数量、耗时、缓存命中和错误类型
```

开机启动标识为 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\DayNest`。恢复普通窗口脚本同样通过主程序的数据读写函数操作 DayNest 配置。

配置和缓存采用唯一临时文件写入后替换，并对 Windows 短暂文件占用进行有限重试。不要将实际运行数据提交到 Git；`.gitignore` 已排除配置、缓存、日志、临时文件和 Python 本地环境。

当前缓存结构直接保存字段完整的事件元数据与独立资源缓存，不包含其他缓存格式的迁移分支。

## 多服务连接

`connection_config()` 统一生成非敏感连接配置，字段为 `provider`、`discovery_url`、`calendar_home_url` 和 `trusted_origins`。iCloud 预设自动使用 `https://caldav.icloud.com/`，不要求用户填写地址；自定义服务支持发现入口、用户地址、直接日历目录，以及可选的目录覆盖。未设置提供商的旧配置按 iCloud 解释。

发现使用 `PROPFIND` 获取 `current-user-principal` 和 `calendar-home-set`，也支持直接从目录列出日历。相对地址按当前响应的实际请求 URL 解析。自定义连接仅允许发现地址、用户填写的目录地址和额外可信地址所属的 HTTPS 来源（域名与端口）；iCloud 允许其已知日历子域。禁止 URL 中嵌入账户密码、降级 HTTP 或跨未授权来源访问。读取显式跟随最多五次重定向，保留 DAV 方法、请求体和 Depth，并逐跳校验；写入不跟随重定向或自动重试。认证仍为 HTTPS Basic，OAuth、DNS SRV 自动查找及 HTTP 连接尚未实现。

缓存记录 `connection` 和 `username`，服务或账户不匹配时不载入旧缓存；缺少服务身份的旧缓存仅适用于 iCloud。切换连接会重置资源缓存、固定项、近期列表和月份任务，失效同步请求标识并递增月份代次。工作线程捕获启动时的连接配置，避免读取修改后的设置。

协议参考：[RFC 4791 日历目录](https://www.rfc-editor.org/rfc/rfc4791.html#section-6.2.1)、[RFC 6764 well-known 地址](https://www.rfc-editor.org/rfc/rfc6764.html#section-5)。

## 同步流程

近期列表读取今天及未来七天。启动后预加载本月及前后各一个月，翻月后继续补载所查看月份的相邻月份。

日程读取分为两步：

1. 通过 `calendar-query` 获取范围内的资源地址与 ETag。
2. 复用版本相同的本地正文；新增或变化的资源通过 `calendar-multiget` 批量读取，每批最多 100 个。批量请求使用相对资源路径。

近期同步与月历共享资源缓存，相邻范围内的同一版本不重复下载。缺少 ETag 时重新读取正文。编辑成功后使相应资源缓存失效，下次读取以服务器内容为准。

每次查询以完整资源列表为准，删除或移出范围的日程不进入新显示结果。不完整响应不会覆盖已有界面数据。读取遇到临时连接中断、超时或部分服务器错误时最多额外重试两次；写入使用 `If-Match` 或 `If-None-Match`，不盲目重试。

月份持久缓存保留实际当前月前后各六个月；更远月份仅暂存。资源内存缓存最多 4000 项，持久化时按保留范围过滤。

日志 `resource sync` 行中的 `reused` 和 `downloaded` 可用于检查正文复用情况。日志不记录邮箱、密码、日程标题或完整资源地址。

实际 iCloud 只读验证中，一个含两条日程的日历冷读取需一次列表和一次正文请求，约 10.3 秒；再次读取且版本未变时只需一次列表请求，正文下载为零，约 5.0 秒。耗时随网络和服务器响应变化。

协议参考：[RFC 4791](https://www.rfc-editor.org/rfc/rfc4791.html#section-7.8)。

## 单实例启动

三个启动入口统一通过 `main()`，在读取或写入配置前获取 Windows 登录会话内的命名互斥量 `Local\DayNest.SingleInstance`。重复启动只显示提示；恢复窗口脚本也不会修改运行中实例的配置。句柄保持到主循环及退出保存完成，并在正常退出或进程终止后由 Windows 释放。互斥量创建失败时停止启动，避免绕过单实例保护。

## 线程与界面

网络工作线程只向结果队列投递结果，主线程验证账户、请求标识和月份任务代次后更新界面与缓存；窗口关闭后不再接收结果。

月份任务使用优先队列与两个工作线程，可见月份优先于相邻预加载月份，月份网络请求限制并发。资源下载协调锁与短期数据锁分开，避免主线程生成快照时等待网络。

近期同步与月份读取使用有并发上限的守护线程，不使用退出时会等待网络工作的线程池。关闭主窗口时设置取消信号、停止后续读取与重试，等待结果的协调线程也会停止；已经阻塞在网络读取中的守护线程不会阻止进程退出。正在写入日程时延迟关闭，等待保存结果后退出。

月历复用 42 个日期格。点击日期只更新原选中格、新选中格和当天详情。未变化的日程卡片与固定卡片不重建；列表刷新会释放点击标签和 Tcl 回调，保持滚动位置。

配色由 `THEMES` 的六套预设和可选十六进制强调色生成，`config.json` 中的 `theme`、`accent` 保存选择，无效值回退午夜蓝及推荐色。设置将外观和账户分为两页，外观可独立保存。预览原位更新 ttk 样式、Tk 控件、文本标签、Canvas 和已有滑块图片，不重建窗口或编辑内容；关闭设置时恢复已保存的主题。新控件使用当前配色，主题色按钮的文字按亮度选择深色或白色。

主组件通过 Tk `-alpha` 设置整体不透明度，`config.json` 的 `opacity` 保存 0.4–1.0 的值，缺失或无效时使用 1.0。设置滑块显示 0%–60% 的透明度并实时预览，关闭设置时恢复配置值；保存后和下次启动沿用新值。其他顶层窗口保持不透明。

桌面模式通过 Windows 前台窗口状态和窗口层级调整显示，不嵌入 Explorer。编辑与设置窗口打开期间暂停主窗口下沉。

## 固定项跟踪

近期同步额外按固定项的日历地址和 UID 发起不带时间范围的 `calendar-query`，同一 UID 在一次同步中只读取一次。单次日程跟随新开始时间和资源地址；重复实例通过 `RECURRENCE-ID` 跟踪，旧固定项从保存的原始 ICS 恢复实例标识。成功查询确认不存在或取消后移除；网络、权限、协议和解析错误保留原值并记录错误类型。结果仅在账户、同步请求和固定项快照仍匹配时应用，与近期列表一起持久化。

协议参考：[RFC 4791 按 UID 查询](https://www.rfc-editor.org/rfc/rfc4791.html#section-7.8.6)。

## iCalendar 数据

支持读取备注、多行转义、折行、时区、跨天事件、`DTEND` 和 `DURATION`。重复集合处理 `RRULE`、日期型 `RDATE`、多个 `EXDATE` 及单次改期或取消；查询范围内超过 5000 条重复实例时明确报错。

以下能力尚未实现：

- 重复日程或全天日程的编辑、事件删除。
- `RANGE=THISANDFUTURE` 和 `RDATE;VALUE=PERIOD`，遇到时明确报错。
- 固定项跨日历移动，以及重复系列整体改期后的实例对应。
- 服务器同步标记；当前仍需获取范围内的完整版本列表。

格式参考：[RFC 5545](https://www.rfc-editor.org/rfc/rfc5545.html)。

## 运行检查

```powershell
python -m pip install -r requirements.txt
python tests/run_checks.py
```

检查采用模拟网络对象，不需要个人账户，不向真实日历服务写入日程。Tk 检查需要有图形桌面的 Windows 会话，会短暂显示窗口。

覆盖范围包括：

- iCloud 预设、自定义地址发现、相对路径与重定向、可信来源校验、条件写入、旧配置及跨服务缓存隔离、服务设置布局。

- 增量下载、重启复用、并发去重、缺失 ETag、删除、分批及不完整响应。
- 后台结果隔离、三个月预加载、模拟启动与备注写入后的完整刷新流程。
- 文件替换中断、并发写入、损坏 JSON 配置处理。
- 重复日程例外与跨天持续时长。
- 备注解析、单行截断、全文显示及编辑字段提交。
- 控件复用、点击回调释放、固定项布局和滚动条交互。
- 子进程级退出验证：近期同步或月份读取模拟阻塞 30 秒时，关闭窗口后进程仍可及时退出；保存过程中关闭则等待写入完成。该检查验证实际进程退出，而不仅是窗口销毁。

## 发布与许可证

源码通过 `DayNest.pyw` 启动，诊断启动错误时可使用 `python daynest.py`。Windows x64 发布版使用 PyInstaller 目录模式和 Inno Setup 7 制作，生成安装版与便携版。用户无需额外安装 Python。

### 构建发布文件

在 64 位 Windows、64 位 Python 3.11 环境中安装 [Inno Setup](https://jrsoftware.org/isdl.php)，然后执行（将 ISCC 路径换成实际位置）：

```powershell
python -m venv .build-env
.\.build-env\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
.\.build-env\Scripts\python.exe tools/build_release.py --iscc "C:\Program Files\Inno Setup 7\ISCC.exe"
```

构建会先执行全部离线检查，生成图标和 Windows 版本信息，打包应用，再运行 EXE 的离线诊断。诊断验证实际冻结运行环境中的 Tk、六套主题、图标、时区、DPAPI、互斥锁与启动命令，不读取账户配置或连接网络。最后生成：

```text
dist/DayNest/                               完整可运行文件夹
release/DayNest-1.0.0-Setup-win-x64.exe      安装包
release/DayNest-1.0.0-Portable-win-x64.zip   便携压缩包
release/SHA256SUMS.txt                      文件摘要
```

`build/`、`dist/`、`release/` 和 `.build-env/` 均不提交 Git。提交 `assets/`、`packaging/`、`tools/`、检查脚本和 `requirements-build.txt`，把发布文件放到 GitHub Releases。

程序通过 `sys.frozen` 区分源码和 EXE 启动方式。开机启动使用实际 EXE 路径；已启用开机启动时，EXE 启动会刷新自己的启动路径，保证程序移动或重新安装后指向实际位置。`DayNest.exe --restore-window` 提供恢复普通窗口入口。图标使用相对模块位置加载，随程序资源一起打包。`DayNest.exe --self-test 报告路径.json` 可独立执行离线运行诊断。

### 安装与卸载

安装范围固定为当前用户，默认目录为 `%LOCALAPPDATA%\Programs\DayNest`，无需管理员权限。提供开始菜单正常启动和恢复入口，以及可选桌面快捷方式。相同 AppId 用于覆盖升级，安装前检查正在运行的 DayNest 实例。

卸载仅删除安装的程序文件。`%APPDATA%\DayNest` 中的账户设置与日程数据保留。只有开机启动项确实指向本次卸载的 EXE 时才清理，不删除其他路径的启动配置。

安装包的隔离验证：

```powershell
.\.build-env\Scripts\python.exe tools/test_installer.py release/DayNest-1.0.0-Setup-win-x64.exe
```

检查使用独立的测试 AppId、测试快捷方式名称及临时安装目录，完成安装、EXE 自检、卸载和数据保留检查；检查后删除测试安装。该检查会短暂创建当前用户的测试卸载记录。

### 图标、依赖与签名

`assets/DayNest.svg`、PNG 和 ICO 为项目生成的原创几何图标，可运行 `tools/generate_icon.py` 重新生成。安装文件夹中的 `licenses/` 保留 Python、python-dateutil、six、PyInstaller、Tcl 和 Tk 的许可文本。部分 Python 安装缺少 Tcl 的独立许可文件，项目随附来自 [Tcl 8.6.12 官方源码](https://github.com/tcltk/tcl/blob/core-8-6-12/license.terms)的文本供构建复制。

当前产物未进行发布者代码签名。创建 EXE 安装包不等于完成签名，Windows 仍可能显示发布者未知或信誉提示。当前选择以无签名方式发布，不依赖付费签名服务。Inno Setup 的使用应遵守其当前许可条款。

DayNest 的项目代码与原创图标采用 GPL-3.0-only，完整许可见根目录 `LICENSE`。构建工具将该文件复制到安装目录和便携包根目录，并保留第三方组件的许可文本。通过 GitHub Releases 分发二进制时，应同时提供与该版本对应的完整源码及构建脚本，例如使用指向同一提交的发布标签与源码归档。


### Glass appearance

New configurations enable `glass` and use `opacity=0.9` (10% transparency). Existing saved opacity values are preserved. The appearance page previews the glass switch immediately; closing without saving restores the saved setting. Windows Acrylic composition uses a theme-tinted backdrop through SetWindowCompositionAttribute, with explicit pointer-sized ctypes signatures. This optional API is not a stable public Windows contract: unavailable or rejected calls leave ordinary Tk transparency available. When Acrylic is accepted, Tk opacity stays at 0.99 to retain its layered surface and the slider adjusts backdrop tint alpha, preserving foreground text. Otherwise ordinary whole-window opacity is used. Forced DWM frame extension is disabled: it caused a blank Tk client area despite successful API returns. Custom shadows remain pending. This is not a Liquid Glass refraction renderer.
