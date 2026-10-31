# Vercel 部署

云端版 v0.6.0 使用 FastAPI + 原生 HTML/CSS/JavaScript + PostgreSQL。Streamlit 的 app.py 继续作为本地入口；Vercel 通过 pyproject.toml 中的 tool.vercel.entrypoint 加载 studypilot.web:app，不导入 Streamlit、不启动子进程，不在函数临时目录创建账号数据库。

## 项目配置

当前 GitHub 仓库：aerixx0/Study_Pilot。

- Root Directory：python-ai-agent-ai-agent-studypilot/outputs/StudyPilot
- Framework Preset：FastAPI（仓库 vercel.json 已指定）
- Install Command：pip install -r requirements.txt
- Build Command、Output Directory：不设置
- Python：3.12 或更新的兼容版本
- 函数最长 120 秒；AI 循环仍保留自己的轮数、工具次数和时间限制。

入口变量是实际 FastAPI 应用，不能把 Streamlit 页面函数改名为 app 来替代。协议与部署方式见 [Vercel Python 入口文档](https://vercel.com/docs/functions/runtimes/python#python-entrypoints) 和 [FastAPI 部署文档](https://vercel.com/docs/frameworks/backend/fastapi)。

## 云端环境变量

在 Vercel 项目设置或 Marketplace 数据库连接中配置，不能放进 Git：

| 变量 | 用途 |
|---|---|
| DATABASE_URL | 必需，PostgreSQL 连接串；也兼容 POSTGRES_URL |
| ZHIPU_API_KEY | 可选，主模型智谱 GLM-4.7-Flash 的密钥 |
| CLOUDFLARE_ACCOUNT_ID | 可选，Cloudflare 账号 ID，32 位十六进制，须与 Token 同时配置 |
| CLOUDFLARE_API_TOKEN | 可选，Cloudflare Workers AI Token，使用 Workers Free 免费套餐 |
| SILICONFLOW_API_KEY | 可选，备用模型硅基流动 Xing4.0-29B 的密钥 |
| STUDYPILOT_AI_USER_LIMIT、STUDYPILOT_AI_WINDOW_SECONDS、STUDYPILOT_AI_SITE_LIMIT | 可选，免费额度保护；默认 15 次 / 账号 / 10 分钟、400 次 / 全站 / UTC 日 |

建议使用数据库提供方的池化 URL，保留提供方要求的 TLS 参数，例如 sslmode=require。生产、预览和开发环境应使用独立数据库或数据库分支；不要把生产连接复制给不受信任的预览部署。没有配置数据库时页面会明确提示，绝不回退到 /tmp SQLite。

可通过 Vercel Marketplace 连接 Neon PostgreSQL。本次选择可用的 Free 套餐 free_v3、iad1 区域、仅连接生产环境；没有为应用启用 Neon Auth，继续使用 StudyPilot 自己的账号和恢复码。具体额度与条款以创建时页面为准，不自动升级付费套餐。

账号表位于 sp_auth schema；每个账号的学习数据位于服务端 UUID 决定的 sp_u_<账号ID> schema。免费 AI 额度的持久化计数（ai_usage、ai_site_usage）也在 sp_auth，冷启动不清零；表由启动时的 CREATE TABLE IF NOT EXISTS 自动补齐，旧库不需要手工迁移。表为原生 PostgreSQL 表，保留任务版本、真实记录、规则计划、提案和执行收据。参数绑定、确认校验和业务规则复用本地版；串行事务锁保证同一提案只有一次提交。函数内存不保存账号数据副本。

登录会话使用 HttpOnly、Secure（Vercel）、SameSite=Strict cookie；会话摘要存在数据库中。修改请求检查同源 Origin 与会话派生 CSRF 凭据。密码、恢复码不会写进浏览器本地存储。退出和换号清空页面草稿及对话；忽略已退出账号的异步响应。

## 部署后核对

1. /api/health 应返回 ok=true，database_configured=true；它只表示运行环境与配置存在，不证明数据库可连接。
2. 实际注册、登录，再保存一项明确标记的测试任务；重新加载后仍可读取，才能验证持久化。
3. 另一个账号应看不到该任务和提案。普通账号不显示开发进度，直接请求 /api/development 返回 403。
4. 未勾选确认不能创建任务或执行提案；重复执行同一提案返回同一收据。
5. 未配置 ZHIPU_API_KEY 且未配置 SILICONFLOW_API_KEY 时 AI 发送按钮禁用；配一个即可用，两个都配才有自动切换。不能把网站上线当作真实模型调用已验证。

本地旧账号和学习库不会随源码上传，也不会自动迁移到云端。云端是独立实例；已有本地数据原样保留。导出的学习 JSON 不包含凭据，当前不支持一键恢复；生产备份应使用 PostgreSQL 提供方的备份与导出能力。

云端开发者权限由维护者在受信任终端执行：

```powershell
# 先在本机安全设置 DATABASE_URL，不要复制连接串到聊天或 Git。
python manage_cloud.py grant-developer 你的云端用户名
python manage_cloud.py revoke-developer 你的云端用户名
```

## 本地运行与测试

```powershell
python -m pip install -r requirements-local.txt
python -m streamlit run app.py
```

测试新版 Web 界面时，可以显式设置 STUDYPILOT_WEB_LOCAL=1 和独立的 STUDYPILOT_AUTH_DIR，再执行 python -m uvicorn studypilot.web:app --host 127.0.0.1 --port 8000。该本机 SQLite 模式在 Vercel 上始终禁用；不设置该变量时 Web 入口要求 PostgreSQL。

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

PostgreSQL 集成测试需要显式的 STUDYPILOT_TEST_POSTGRES，只允许本机隔离测试数据库；不设置时跳过该组。不得使用生产库。测试仅创建临时账号，不读取用户真实数据。


免费模型接入与 Vercel 密钥配置详见 [FREE_AI_ENGINE.md](FREE_AI_ENGINE.md)。
