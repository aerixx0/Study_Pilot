# StudyPilot

中文学习管理网站：账号隔离、学习任务与真实用时、规则式每周计划、免费国产模型（主 GLM-4.7-Flash，备用 Xing4.0-29B）只读工具与修改提案。修改由用户核对确认后执行。

云端版使用 FastAPI + PostgreSQL，部署在 Vercel；保留本地 Streamlit + SQLite 入口。

- Vercel Root Directory：`python-ai-agent-ai-agent-studypilot/outputs/StudyPilot`
- Framework：FastAPI，入口在子目录的 pyproject.toml 中明确配置
- 云端依赖：该目录的 requirements.txt
- 必需环境变量：DATABASE_URL（PostgreSQL）
- AI 可选环境变量：ZHIPU_API_KEY（主模型）、SILICONFLOW_API_KEY（备用模型）；都没有则不启用 AI，也不会回退到收费服务

[部署说明](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/DEPLOYMENT.md) · [完整说明](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/README.md) · [验证记录](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/VALIDATION.md)

本地数据与密钥不随源码上传。Vercel 不使用临时 SQLite 保存账号资料。
