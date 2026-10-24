# StudyPilot · 运行与配置

把目标、任务、每周计划和真实学习记录放在同一个工作空间，让每一步学习都有依据。

[在线使用](https://study-pilot-olive.vercel.app/) · [产品介绍](../../../README.md) · [English](README.en.md) · [部署指南](DEPLOYMENT.md)

## 使用流程

1. 创建账号，妥善保存仅显示一次的恢复码。
2. 设置学习目标、可用时间、设备与偏好，核对后保存。目标可以暂时留空。
3. 添加任务，设置优先级、截止日期与预计用时。
4. 根据每周预算和每日条件生成计划预览，确认后保存。
5. 在实际学习后记录用时，通过图表查看投入与进度。

网站支持中文与英文、亮暗主题和手机布局。对话可协助查询进度、讨论目标和提出计划建议；正式修改始终需要用户确认。

## 在本地运行 Web 版

准备 Python 3.12 或更新的兼容版本。在本目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:STUDYPILOT_WEB_LOCAL = "1"
.\.venv\Scripts\python.exe -m uvicorn studypilot.web:app --host 127.0.0.1 --port 8510
```

打开 [本地 Web 界面](http://127.0.0.1:8510/)。此模式使用 SQLite，支持中英文切换；关闭服务后，已保存的数据仍保留在本地。

若希望使用中文 Streamlit 界面，可运行本目录的 `Start-StudyPilot.cmd`，或执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe start_studypilot.py
```

本地数据默认位于 `data/accounts/`。备份时请保留数据目录；账号凭据、密钥、数据文件和虚拟环境不应提交到 Git。

## 自行部署 Web 版

Web 版采用 FastAPI 和原生 HTML、CSS、JavaScript；云端使用 PostgreSQL 持久化。

| 配置项 | 值 |
| --- | --- |
| Vercel 项目根目录 | `python-ai-agent-ai-agent-studypilot/outputs/StudyPilot` |
| 服务端入口 | `studypilot.web:app`，由 `pyproject.toml` 指定 |
| 运行依赖 | `requirements.txt` |
| 数据库 | `DATABASE_URL`，兼容 `POSTGRES_URL` |

具体设置、环境隔离与部署核对见 [DEPLOYMENT.md](DEPLOYMENT.md)。云端不会使用临时 SQLite 保存账号数据；本地与云端实例的账号和学习数据不会自动同步。

## 可选 AI 服务

对话支持日常交流、目标教练和计划构建三种模式。模型接入由服务端管理，客户端不能指定任意服务地址或模型。

| 环境变量 | 用途 |
| --- | --- |
| `ZHIPU_API_KEY` | 主模型服务密钥 |
| `SILICONFLOW_API_KEY` | 备用模型服务密钥 |
| `STUDYPILOT_AI_ENABLED` | 设为 `0` 可暂停模型调用 |

密钥应配置在服务进程或托管平台的环境变量中。项目不会自动加载 `.env` 文件；[.env.example](.env.example) 仅提供变量名称说明。

未配置模型密钥时，学习管理功能仍可使用。启用 AI 后，每次请求需同意向列出的模型服务商发送本次问题、对话上下文及相关学习资料；账号凭据不包含在内。

所有修改都经过“提出建议 → 核对内容 → 用户确认 → 服务端验证”流程。提案有有效期和版本检查，重复提交不会重复写入。AI 不会根据计划推定真实学习用时，也不能通过聊天中的“确认”直接执行更改。

模型白名单、故障恢复、限流与额度控制见 [FREE_AI_ENGINE.md](FREE_AI_ENGINE.md)。服务可用性与费用政策以提供方当前规则为准。

## 数据与账号管理

- 各账号拥有独立的学习档案、任务、记录、计划和提案。
- 支持注册、登录、退出、密码修改、恢复码重置及登录会话管理。
- 支持修改昵称、头像标识、个性签名和登录用户名。
- 可导出自己的学习数据；导出不包含密码、恢复码或登录令牌。
- 删除任务会保留已发生的学习记录；计划与预计用时不会自动计入实际统计。
- 网站切换语言会保留草稿，不翻译或改写用户原文。语言选择保存在当前浏览器中。

## 测试与维护

安装测试依赖后，在本目录运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用临时账号和独立测试数据，模型异常场景使用 Mock。PostgreSQL 集成测试需单独配置测试数据库，否则会明确跳过；配置方法见部署指南。

界面语言词典位于 `public/i18n.js`，服务端提示位于 `studypilot/i18n.py`。翻译仅用于界面文字，用户内容和数据库标准值保持原样。

## 开源许可

项目代码采用 [MIT License](LICENSE)。第三方模型与托管服务按各自的条款和服务政策使用。
