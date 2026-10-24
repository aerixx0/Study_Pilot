<div align="center">

# StudyPilot

### 把想学的，变成做到的。

让目标有方向，让计划可执行，让每一份投入看得见。

[在线使用](https://study-pilot-olive.vercel.app/) · [English](README.en.md) · [部署指南](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/DEPLOYMENT.md) · [MIT License](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/LICENSE)

</div>

---

StudyPilot 是一款支持中文与英文的学习管理工具，将学习目标、任务、每周计划和真实用时集中在一个工作空间。无论是准备考试、学习新技能，还是推进长期自学项目，都可以从明确下一步开始，逐步建立适合自己的学习节奏。

## 为持续学习而设计

| 你希望做到的事 | StudyPilot 如何帮助你 |
| --- | --- |
| 明确方向 | 维护自己的学习目标与偏好；尚未确定的目标可以留空。 |
| 推进任务 | 设置优先级、截止日期和预计用时，跟进完成状态。 |
| 合理安排时间 | 根据每周预算、每天可用时间及设备条件，生成可预览、可确认的每周计划。 |
| 看见真实进步 | 记录实际学习时间，通过图表查看每周投入与科目分布。 |
| 获得学习建议 | 在对话中梳理目标、查询进度和讨论计划，核对建议后再应用更改。 |

## 从计划到行动，一处完成

- **独立的个人空间**：账号分别管理档案、任务、记录和计划，支持昵称、个人资料与账号安全设置。
- **适应你的学习条件**：把可用时间、设备和学习偏好纳入安排，而不是套用固定模板。
- **以真实投入衡量进度**：预计用时、任务完成和实际学习记录分别管理，统计来自实际记录。
- **由你决定是否修改**：目标、任务与计划的变更需明确确认；AI 建议不会直接覆盖正式数据。
- **中英文使用体验**：网站支持语言切换、亮暗主题、响应式布局，以及独立的对话工作区。
- **灵活的运行方式**：可以在线使用，也可以自行部署或在本地运行。

## 开始使用

1. [打开 StudyPilot](https://study-pilot-olive.vercel.app/)，创建账号并妥善保存恢复码。
2. 完善学习档案，设置每周预算、每日可用时间和设备，确认保存。
3. 添加任务，预览并保存每周计划；完成学习后记录真实用时。

网站右上角可选择 **中文 / EN** 和亮暗主题。首次访问会参考浏览器语言，手动选择会在当前浏览器中保留。

## 让 AI 参与讨论，让你保留决定权

对话支持日常学习交流、目标梳理与每周计划建议。AI 可读取当前账号的相关学习资料，并将修改整理成待确认提案。

**了解情况 → 提出建议 → 核对差异 → 确认应用**

没有确认，就不会执行提案。聊天中的一句“确认”也不能替代提案卡片上的确认操作。

AI 功能需要服务端配置模型密钥，并在使用前征得本次资料发送的同意。未启用 AI 时，学习档案、任务、规则式计划和用时记录仍可使用。配置与调用边界见 [AI 接入说明](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/FREE_AI_ENGINE.md)。

## 选择适合你的使用方式

| 方式 | 适用场景 | 说明 |
| --- | --- | --- |
| [在线使用](https://study-pilot-olive.vercel.app/) | 希望直接开始管理学习 | 浏览器访问，支持中文与英文。 |
| 自行部署 Web 版 | 希望管理自己的服务与数据 | FastAPI + PostgreSQL，可部署至 Vercel。 |
| 本地运行 | 希望在自己的电脑上使用 | SQLite 持久化；可选择双语 Web 界面或中文 Streamlit 界面。 |

不同部署实例的账号和数据相互独立。本地记录不会自动上传到线上，也不会自动与其他实例同步。

## 文档与项目资源

- [本地运行与配置](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/README.md)
- [Vercel 与数据库部署](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/DEPLOYMENT.md)
- [AI 接入与额度控制](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/FREE_AI_ENGINE.md)
- [环境变量示例](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/.env.example)
- [自动化测试](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/tests/)

账号凭据与学习数据按现有鉴权和隔离规则管理。API Key 仅由服务端读取，不放入客户端代码；用户可在账号设置中导出自己的学习数据。导出内容不包含密码、恢复码或登录令牌。

## 开源许可

StudyPilot 项目代码采用 [MIT License](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/LICENSE)。第三方模型与托管服务按各自的条款和服务政策使用。
