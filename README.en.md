<div align="center">

# StudyPilot

### Turn learning into progress.

Give your goals direction, make room for learning, and see your effort add up.

[Open StudyPilot](https://study-pilot-olive.vercel.app/) · [简体中文](README.md) · [Self-hosting guide](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/DEPLOYMENT.md) · [MIT License](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/LICENSE)

</div>

---

StudyPilot brings your learning goals, tasks, weekly plans, and actual study time into one workspace. Whether you are preparing for an exam, learning a new skill, or working through a longer project, start with a clear next step and build a rhythm that fits your life.

## Built for steady progress

| What you want to do | How StudyPilot helps |
| --- | --- |
| Find your direction | Keep your own goals and learning preferences. Leave goals blank until you are ready. |
| Move tasks forward | Set priorities, due dates, and estimates, then track completion. |
| Make time for learning | Preview a weekly plan based on your time budget, daily availability, and devices. |
| See your actual effort | Log study time and review weekly totals and time by subject. |
| Think through the next step | Discuss goals, progress, and plans in Chat, then review suggestions before applying changes. |

## One workspace, from intention to action

- **Your own learning space.** Each account has its own profile, tasks, records, and plans, with personal details and account security settings.
- **Plans that reflect your constraints.** Use your available time, devices, and preferences to guide scheduling.
- **Progress grounded in actual study.** Estimates, task completion, and time records are kept separate. Time statistics come from actual records.
- **Changes stay under your control.** Review and confirm changes to goals, tasks, and plans. AI suggestions do not overwrite saved data automatically.
- **English and Simplified Chinese.** Switch languages, choose a light or dark theme, and use a responsive interface with a dedicated chat workspace.
- **Flexible hosting.** Use the hosted website, deploy your own Web instance, or run locally.

## Get started

1. [Open StudyPilot](https://study-pilot-olive.vercel.app/), create an account, and save your recovery code privately.
2. Review your learning profile. Set a weekly time budget, daily availability, and devices, then confirm saving.
3. Add tasks, preview and save a weekly plan, and log time after studying.

Choose **EN** in the top-right corner. On your first visit, the website follows your browser language; your manual choice is remembered in that browser.

## Discuss with AI. Decide for yourself.

Chat supports general learning conversations, goal coaching, and weekly planning suggestions. With your consent, AI can use relevant learning data from your account and prepare proposed changes for review.

**Understand → Suggest → Review → Confirm**

Suggestions require explicit confirmation on their cards. Saying “confirm” in chat does not apply a change.

AI requires server-side provider configuration and consent to share the relevant data for each request. Profiles, tasks, rule-based plans, and study records remain available when AI is disabled. See the [AI integration guide](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/FREE_AI_ENGINE.md) for configuration and limits.

## Choose how to use StudyPilot

| Option | Best for | Details |
| --- | --- | --- |
| [Hosted website](https://study-pilot-olive.vercel.app/) | Getting started in a browser | English and Simplified Chinese. |
| Self-hosted Web app | Managing your own instance and data | FastAPI with PostgreSQL; supports deployment to Vercel. |
| Local use | Running on your own computer | SQLite storage, with a bilingual Web interface or a Chinese Streamlit interface. |

Accounts and data are separate across deployments. Local records are not automatically uploaded or synchronized with the hosted website.

## Documentation

- [Local setup and configuration](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/README.en.md)
- [Vercel and database deployment](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/DEPLOYMENT.md)
- [AI providers and quota controls](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/FREE_AI_ENGINE.md)
- [Environment variable example](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/.env.example)
- [Automated tests](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/tests/)

Authentication and account isolation apply to learning data and account operations. API keys are read only on the server. You can export your own learning data from account settings; exports exclude passwords, recovery codes, and session tokens.

## License

StudyPilot's project code is distributed under the [MIT License](python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/LICENSE). Third-party models and hosting services are subject to their own terms and policies.
