# 在 Windows 上使用 StudyPilot

## 安装和打开

1. 双击 `StudyPilot-Windows-x64-Setup.exe`，按安装向导继续。适用于 Windows 10/11 x64，正常安装使用当前 Windows 账户。
2. 可在向导中勾选 **Create a desktop shortcut / 创建桌面快捷方式**。
3. 在开始菜单搜索并打开 **StudyPilot**。本地服务就绪后会打开系统默认浏览器。已有本地账号可用原密码登录。新账号注册后请保存恢复码。本地版设置、修改和重置密码均接受 6–128 个字符。

安装包包含 Python、Streamlit 和 SQLite。核心学习管理和安装过程可以离线使用。云端 AI 需要联网并连接网页版账号。

StudyPilot 常用地址为 `http://127.0.0.1:8501/`。端口占用时默认尝试后续端口，浏览器会打开实际地址。若浏览器未能启动，弹出的窗口会显示可手动打开的地址。重复打开快捷方式会复用当前用户的服务。

## 本地 AI 配置

在本地工作台点 **AI 助手** 会直接打开与网页版共用的对话界面，沿用当前本地账号。对话仍由本机的学习数据和 AI 配置提供服务。

本机 Qwen3.5-4B 由随 StudyPilot 服务开关的 llama.cpp 运行。模型无需 API Key，默认在电脑上处理对话。运行时和模型文件单独保存在 `%LOCALAPPDATA%\StudyPilot`，不需要每次升级重新下载。

- 模型文件路径为 `models\Qwen3.5-4B-Q4_K_M.gguf`，Windows x64 llama.cpp 的 `llama-server.exe` 和依赖放在 `llama.cpp` 目录。
- 可选 Cloudflare 备用为 `@cf/openai/gpt-oss-20b`。打开开始菜单的 **配置 StudyPilot AI**，输入 Cloudflare Account ID 和 Workers AI API Token。凭据保存在 Windows 凭据管理器。请使用 Workers Free。[Cloudflare 额度说明](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- 用 `studypilot ai status` 或对话页的 **本地 AI 连接状态** 查看本机模型是否就绪。使用 Cloudflare 备用时，已同意使用的相关学习资料可能发送给 Cloudflare。

### 网页与 Windows 版共用云端 AI
网页版的「对话」支持选择 Qwen、GPT-OSS 或自动选择。Windows 用户在 AI 助手点「连接云端 AI」，登录网页版后在「账号设置 → 连接 Windows 版 AI」生成一次性连接码，再粘贴回本地「账号设置 → 云端 AI」。普通用户无需 Cloudflare 账号或 API Key。窗口内可以重新连接或断开，网页版可撤销所有桌面授权。

已安装的本机 Qwen 可以继续离线使用。CLI 可用 `studypilot ai ask "帮我总结一下学习进度" --model qwen` 或 `--model gpt-oss` 选择模型，省略参数时自动选择。云端请求需要联网并受账号与全站额度限制。

## 停止、卸载和重新安装

在开始菜单打开 **停止 StudyPilot**。关闭浏览器标签页以后服务仍会运行，停止后可随时再次打开。也可以运行 `studypilot stop`。

在 Windows **设置 → 应用 → 已安装的应用** 中卸载。卸载会停止服务并移除程序和快捷方式，学习记录和备份会保留。用同一 Windows 账户重新安装后可继续使用原本地账号。

## 数据、备份和旧版导入

| 内容 | 默认位置 |
| --- | --- |
| SQLite 账号和学习数据 | `%LOCALAPPDATA%\StudyPilot\data\accounts` |
| 备份 | `%LOCALAPPDATA%\StudyPilot\backups` |
| 可选的端口配置 | `%LOCALAPPDATA%\StudyPilot\settings.json` |
| 当前及上一次启动日志 | `%LOCALAPPDATA%\StudyPilot\logs` |

旧版项目或 ZIP 版中的 `data\accounts` 可在开始菜单选择 **导入旧版 StudyPilot 数据**。先关闭两边的服务，再选择旧项目、`data` 或 `accounts` 文件夹。导入会复制账号和学习数据，源目录会保留。如果新位置已有账号或学习数据，导入会停止。导入后使用原有账号登录。

只有一个旧 `studypilot.db` 的版本可先在新应用注册空账号，再停止服务并使用下方 `data import-legacy` 命令。账号和记录仅在本机使用，网页版有独立的账号和数据。

## CLI

安装后打开一个新的 PowerShell 或命令提示符。业务命令会要求本地账号登录，密码在终端中输入且不回显。对修改操作，输入 `y` 确认，其余输入默认取消。

| 命令 | 用途 |
| --- | --- |
| `studypilot --help` | 查看命令和帮助。子命令也支持 `--help`。 |
| `studypilot start` | 启动服务和默认浏览器。支持 `--no-browser` 和 `--port PORT`。 |
| `studypilot status` | 显示运行地址和 PID。退出码 0 表示运行，1 表示停止，2 表示启动中或无响应。 |
| `studypilot stop` | 停止当前数据目录所管理的服务，可重复运行。 |
| `studypilot task list` | 列出任务。另有 `add`、`edit`、`delete`。 |
| `studypilot plan preview --week 2026-11-23` | 预览指定周，需先在浏览器保存学习档案。用 `show` 查看已保存的计划，用 `save` 预览并确认保存。 |
| `studypilot record add 1 25` | 给任务 1 记录当天 25 分钟。另有 `list` 和 `delete`。 |
| `studypilot ai ask "下一步学什么？"` | 经同意后联系已配置的 AI。另有 `proposals`、`apply ID`、`reject ID`。 |
| `studypilot data path` | 查看数据、备份、配置和日志路径。 |
| `studypilot data backup` | 停止服务后生成 SQLite 备份。 |
| `studypilot data migrate "D:\旧版 StudyPilot"` | 停止新旧服务后，把旧账号库复制到空的数据目录。可用同一命令从备份恢复到独立、空的数据目录。 |
| `studypilot data import-legacy "D:\旧版\data\studypilot.db"` | 停止服务后，把单文件旧版库导入已注册的空账号。 |

例子：

```powershell
studypilot task --user "我的账号" add --title "做一组练习" --subject Python --due 2026-11-23 --minutes 30
studypilot task edit 1 --status 已完成
studypilot record list
studypilot ai proposals
studypilot ai apply PROPOSAL_ID
```

AI 修改会展示提案内容并单独询问确认。CLI 和浏览器使用同一套账号验证、版本检查与写入规则。本地凭据优先通过「配置 StudyPilot AI」设置。开发者也可在启动环境中设置 CLOUDFLARE_ACCOUNT_ID 和 CLOUDFLARE_API_TOKEN。[AI 配置](README.md#ai-configuration-and-confirmation)

如果需要固定端口，在数据目录下创建 UTF-8 的 `settings.json`，写入例如 `{"port": 8510}`。从源码调试时可用 `STUDYPILOT_HOME` 指向单独的测试目录。用 `--port` 或配置固定端口时，端口被占用会提示失败。服务器默认只监听 `127.0.0.1`。