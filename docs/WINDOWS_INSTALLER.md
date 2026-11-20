# StudyPilot Windows 安装包与验收

## 交付

- 安装程序为 `verification/StudyPilot-Windows-x64-Setup.exe`，大小约 81.2 MiB。同目录有 SHA-256 校验文件。
- 构建使用 Inno Setup 6.7.3、Python.org 发布的 x64 嵌入式 CPython 3.13.14，以及锁定版本的 Windows wheels。构建需要联网取得依赖或使用构建缓存。已有锁定版本的 wheels 时可用构建参数 --wheelhouse 指向本地目录。安装和核心学习功能可离线使用。[Inno Setup](https://jrsoftware.org/inno-setup/downloads) · [CPython 发布与校验值](https://www.python.org/downloads/release/python-31314/)
- 安装程序默认写入 `%LOCALAPPDATA%\Programs\StudyPilot`，创建每用户开始菜单入口，桌面入口可选。卸载停止本地服务并保留 `%LOCALAPPDATA%\StudyPilot` 下的 SQLite 数据、配置和备份。
- 本地浏览器入口运行既有 Streamlit 页面。业务 CLI 复用账号验证、任务、排程、学习用时和 AI 提案逻辑。网页部署使用原有的 FastAPI 入口和 PostgreSQL 数据隔离机制。

## 0.6.6 网页与 Windows 版共用云端 AI

网页版启用共享 AI 后，对话可选择 Cloudflare Qwen 3.8 27B、GPT-OSS 20B 或自动选择。新安装的 Windows 版可在「账号设置 → 云端 AI」连接网页版。先在网页版「账号设置 → 连接 Windows 版 AI」生成一次性连接码，再把码粘贴回本地版。连接码十分钟有效，桌面授权三十天有效。已安装的本机 Qwen3.5-4B 可以离线使用，选择 Qwen 时优先使用本机模型。现有 Windows Cloudflare 凭据也可继续使用。

云端 Cloudflare Token 仅存生产环境，Windows 只持有绑定到当前本地账号的推理授权。站点和桌面共用账号与全站额度。客户端每次对话仍须确认是否发送问题及相关数据，AI 提案仍须单独确认。网页版可撤销该账号的桌面授权。

生产配置在 FastAPI 所在的 Vercel 项目设置 `STUDYPILOT_SHARED_AI=1`、`CLOUDFLARE_ACCOUNT_ID` 和敏感变量 `CLOUDFLARE_API_TOKEN`，保留现有 PostgreSQL 连接。建议使用 Workers Free 并测试共享额度。生产配置和部署须经项目维护者确认。

本次验证了安装包构建与 SHA-256、原地升级和原账号数据保留、安装版浏览器工作台、两个真实云端模型经 Web 对话和桌面授权接口返回答复、连接码重放拒绝、令牌权限范围、共享限流、撤销授权和未同意时拒绝提交。授权与限流另在本机隔离 PostgreSQL 测试库通过，数据库可用时 216 项回归全部通过。

2026-11-20，Vercel 生产服务已启用共享 AI。正式切换前，两个模型都在同一生产构建中经网页对话和桌面授权接口返回真实答复。Qwen 的一次转发请求超时，重试通过。正式切换后重新验证了公开域名的首页资源、健康检查，以及接受无浏览器 Origin 的桌面授权端点。[生产站点](https://study-pilot-olive.vercel.app/)

涉及的文件包括应用目录下的 `studypilot/ai.py`、`relay.py`、`web.py`、`auth.py`、`postgres.py`、`quota.py`、`windows_credentials.py`、`cli.py`，以及 `public/study.js`、`public/i18n.js`、`tests/test_shared_ai.py` 和安装版本配置。

## 0.6.5 共用网页版对话界面

本地工作台打开原版 HTML、CSS、JavaScript，由同一账号的短时一次性凭证进入网页版对话视图。额外的本机启动脚本只选择初始页面。已用独立测试账号在 Chrome 验证从本地登录进入 Web 对话、侧栏、快捷提问、窄窗口菜单和返回概览。同一模拟账号和窗口尺寸下，直接进入桌面对话与从 Web 概览进入对话的截图像素一致。已用真实本机 Qwen 测试 Web 对话接口。

## 0.6.4 本机 Qwen

Windows 本地助手首选本机 Qwen3.5-4B，通过 llama.cpp 的回环 API 运行，无需 API Key。Windows 作业对象负责随 StudyPilot 一起结束模型进程。模型和原生运行时单独安装在当前用户的数据目录。

本机已核验运行时和模型文件的 SHA-256，并通过实际中文问答、真实只读任务工具调用和关闭进程验证。Cloudflare 保留为可选备用，本机缺少凭据，未发起真实云端请求。

## 0.6.3 本地导航与 AI

桌面浏览器进入 AI 助手时，主要导航滑到左侧，窄窗口可通过左上角按钮展开导航。浏览器测试覆盖桌面、窄窗口、退出对话和减少动态效果。

本地默认先用硅基流动 Qwen3.5-4B，Cloudflare Workers AI 的 GPT-OSS 20B 用作备用。开始菜单安装「配置 StudyPilot AI」入口，凭据由 Windows 凭据管理器保存。已验证一次性测试凭据的读写，以及使用模拟响应的主备切换与工具调用。当前本机缺少真实服务凭据，未调用服务商。已验证 0.6.2 原地升级、服务重启和本地账号任务保留。

## 0.6.2 对话页

本地 AI 助手采用接近网页版的欢迎区、快捷提问、可滚动消息区和独立输入栏。新建对话重置当前对话和输入内容，已有提案仍可继续审阅。发送失败后可重试原问题。

Python 回归测试 193 项通过，17 项 PostgreSQL 测试跳过。对话测试使用模拟模型，覆盖快捷提问、清空对话、发送前确认、连接失败保留草稿以及提案提交。

## 0.6.1 更新验证

- 本地 Streamlit 注册、修改密码和恢复码重置接受 6–128 个字符。页面回归覆盖恰好 6 个字符成功、5 个字符被拒，以及使用新密码登录。
- 在 Windows 11 上将正在运行的 0.6.0 安装原地升级到 0.6.1。核对了账号、凭据摘要和学习数据，重启后可从本机访问。另用 SQLite 备份方式将旧项目的原有本地账号库复制到新版用户目录。
- 0.6.1 的 Python 回归结果为 191 项通过、17 项 PostgreSQL 测试跳过。

## 首版安装与卸载验证

在 Windows 11 x64 上使用独立的安装目录、数据目录和测试账号。安装程序以普通权限运行。测试进程的 PATH 中没有 Python、Python Launcher 或 pip，另外传入了无效的 `PYTHONHOME`。未使用项目现有的学习数据和 AI 凭据。

| 项目 | 结果 |
| --- | --- |
| 安装包构建、安装及独立运行 | 通过。安装到含中文和空格的路径，实际运行了包内 CPython 3.13.14。安装日志显示无管理员权限。 |
| 开始菜单与可选桌面图标 | 通过。通过 Windows ShellExecute 打开安装程序生成的快捷方式，观察到默认 Chrome 新标签页显示 StudyPilot 标题及回环地址。 |
| 服务 CLI 和异常场景 | 通过。`--help`、`start`、`status`、`stop`，包含重复与并发启动、端口占用后切换、显式端口冲突提示、崩溃后恢复。占用端口的其他服务保持运行。用模拟错误验证了浏览器启动失败后提示手动访问地址。 |
| 学习功能和重启 | 通过。在安装版终端交互测试了任务创建、查询和编辑、计划预览与确认保存、记录时长。重启后仍可读取数据。 |
| AI 确认 | 通过。使用测试提案，拒绝时任务未变化，确认后执行成功。既有模型模拟测试也覆盖了提案和账号隔离。 |
| 备份和旧数据 | 安装版 CLI 备份通过。源代码测试验证了账号库复制、目标有数据时拒绝覆盖，以及单库旧版通过 CLI 导入空账号，且保留源数据库和备份。 |
| 卸载 | 通过。从运行状态卸载，确认服务停止、快捷方式和安装包添加的 PATH 项移除，SQLite 文件逐字节一致，备份保留。 |
| 回归 | Python 测试共 208 项，191 通过，17 项需要独立 PostgreSQL 实例而跳过。Python 编译检查、JavaScript 语法检查及浏览器辅助逻辑的 14 项断言通过。 |

## 已知限制和未验证项

- 当前没有可用的干净 Windows 虚拟机。本次覆盖了现有 Windows 11 主机上的隔离安装和无系统 Python 搜索路径场景。全新 Windows、物理上未装 Python、Windows 10和 ARM64 仍待独立验收。
- 已观察到默认浏览器的 StudyPilot 标签页。自动化工具未获得读取 127.0.0.1 页面内容的权限，未执行浏览器表单操作。安装测试使用静默模式，未逐屏操作安装向导。开始菜单的旧数据文件夹选择框未做交互验收。
- 安装程序未做 Authenticode 签名。实际 AI 服务调用、托管 PostgreSQL 和线上部署未进行。安装版 Streamlit 界面使用简体中文。
- 多账号迁移面向空目标目录，暂不合并账号库。恢复到空目录前应停止本地服务，并将备份保存在安全位置。

## 文件清单

| 路径 | 内容 |
| --- | --- |
| `README.md`、`Usage.md`、`docs/WINDOWS_INSTALLER.md` | 安装、源码和 CLI 用法、数据迁移及验收记录 |
| `scripts/build_windows_installer.py` | 构建、校验与打包流程 |
| `scripts/windows/StudyPilot.iss`、`scripts/windows/Launcher.cs` | 每用户安装卸载、快捷方式和独立 CLI 启动器 |
| 应用目录的 `requirements-windows.txt`、`pyproject.toml` | 安装包依赖与可编辑源码安装入口 |
| 应用目录的 `Start-StudyPilot.cmd`、`start_studypilot.py` | 源码和已安装应用启动入口 |
| `studypilot/cli.py`、`studypilot/local_service.py`、`studypilot/windows_ui.py` | 命令、服务生命周期和快捷方式提示 |
| `studypilot/local_paths.py`、`studypilot/local_data.py` | 用户目录、SQLite 备份和迁移 |
| `tests/test_local_cli.py`、仓库 `.gitignore` | CLI 回归覆盖，忽略本地构建元数据 |

应用目录为 `python-ai-agent-ai-agent-studypilot/outputs/StudyPilot`。
