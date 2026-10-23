# Free AI Engine v1.0

沿用 Python FastAPI + 原生网页和本地 Streamlit。无 Next.js、Vite 或 npm 构建步骤。服务端入口为 `/api/agent`，适配器为 `studypilot/ai.py`，工具循环为 `agent.py`，持久化限流为 `quota.py`。现有动效、鉴权、学习档案和提案确认流程继续使用。

## 模型与配置

| 顺序 | 固定端点 | 固定模型 | 服务端变量 |
|---|---|---|---|
| 主用 | https://open.bigmodel.cn/api/paas/v4/chat/completions | glm-4.7-flash | ZHIPU_API_KEY |
| 备用 | https://api.siliconflow.cn/v1/chat/completions | XingChenAGI/Xing4.0-29B | SILICONFLOW_API_KEY |

2026-10-23 核对：[GLM 模型文档](https://docs.bigmodel.cn/cn/guide/models/free/glm-4.7-flash)、[智谱价格](https://bigmodel.cn/pricing)、[硅基流动价格](https://siliconflow.cn/pricing)。只使用精确模型白名单，不接受客户端地址或模型选择，不读取旧 OPENAI_API_KEY 作为兜底。服务商以后可能调整定价，应定期复核；需要停用时设置 `STUDYPILOT_AI_ENABLED=0`。开源权重与托管 API 免费是不同概念。

环境变量示例见 `.env.example`，只有空变量名，不包含密钥。程序不自动加载 `.env`。本机通过启动进程的环境变量配置；Vercel 在项目 Settings → Environment Variables 的 Production 环境设置两把 Key 后重新部署。不要把密钥发到聊天或提交 Git。未配 Key 时界面禁用发送，只配一家时可以单独使用。

## 恢复与业务边界

主模型仅在 429、超时、连接失败、5xx 时尝试备用。主备共用每轮最多 20 秒的超时预算，失败的服务不在后续工具轮次重试。认证、非法请求、截断或结构错误直接拒绝。最多 6 轮、12 次工具调用。请求固定非流式，完整校验后才展示，不会在输出部分文本后切换模型。

提供 chat、goal_coach、plan_builder 三种模式；后两种缩小可用工具范围。工具参数由原 JSON Schema、版本与业务规则校验。所有正式目标、任务、记录和计划的写入继续要求用户勾选确认及服务端事务验证，聊天中的确认不能执行提案。

日志只包含服务商、模型、耗时、状态码和错误类型，不记录消息、学习资料或密钥。

## 持久化额度

默认每账号 15 次 / 600 秒固定窗口，全站 400 次 / UTC 日。每次有效对话先原子预占一次，失败不退款；未认证、非法参数或未配 Key 不消耗配额。计数保存在本地账号 SQLite 或云端 sp_auth 的新增表，启动自动补齐，原学习数据无需搬迁。跨进程、冷启动共用数据库计数，超限返回 429。

可通过 STUDYPILOT_AI_USER_LIMIT、STUDYPILOT_AI_WINDOW_SECONDS、STUDYPILOT_AI_SITE_LIMIT 设置代码范围内的正整数。该配额计数单位为对话请求，单次请求可能包含多轮模型调用；不是服务商 token 余额。所有轮次都有输出和时间上限。

## 检查与部署

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m compileall -q studypilot app.py
node --check public/study.js
node --check public/motion.js
```

完整 PostgreSQL 回归将 STUDYPILOT_TEST_POSTGRES 指向本机隔离数据库，禁止使用 Neon 生产库。Mock 测试覆盖两家正常/异常响应、恢复策略、目标待确认、非法输出、模式、未认证、并发与重启后的额度；不消耗真实模型请求额度。

Vercel 保持原 Root Directory、FastAPI 入口和 PostgreSQL 配置，详见 DEPLOYMENT.md。云端构建仍通过 pyproject.toml 安装 Python 依赖。配置真实 Key 后，先用只读问题核验账户权限、免费状态及真实工具调用；Mock 通过不代表真实模型调用已经验证。
