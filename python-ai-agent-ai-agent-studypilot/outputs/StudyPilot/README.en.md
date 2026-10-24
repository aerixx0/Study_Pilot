# StudyPilot

Manage learning goals, tasks, weekly plans, and actual study time. The Web app supports English and Simplified Chinese, with light and dark themes and a dedicated chat workspace.

[Open StudyPilot](https://study-pilot-olive.vercel.app/) · [Product overview](../../../README.md) · [Application guide](README.md)

## Getting started

Open the deployed website and choose **EN** in the top-right corner. On your first visit, StudyPilot follows your browser language. Your manual choice is remembered in that browser.

1. Create an account and save your recovery code somewhere private. It is shown only once.
2. Review your learning profile. Set your available time and devices, then confirm saving. Goals can stay blank.
3. Create tasks with priorities, due dates, and estimates. Preview and confirm a weekly plan.
4. Log study time only after the study actually happened. Estimates and plans do not count as actual time.
5. Use Chat to discuss progress, goals, or plans when a model provider is configured. Review and explicitly confirm each proposed change before it can be applied.

Switching language keeps form drafts and preserves your own writing. Existing goals, task titles, notes, and conversations stay in their original language. AI is instructed to reply in your selected language; previously generated replies are not rewritten.

## Running the Web app locally

Use Python 3.12 or later. From this application directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:STUDYPILOT_WEB_LOCAL = "1"
python -m uvicorn studypilot.web:app --host 127.0.0.1 --port 8510
```

Open `http://127.0.0.1:8510/`. Local Web accounts use SQLite. The separate Streamlit interface remains Chinese; the language switch is available in the Web app.

For Vercel, follow [deployment instructions](DEPLOYMENT.md). Production uses PostgreSQL and requires a configured database. Local accounts are not automatically copied to the cloud.

## AI and privacy

Provider keys are read only from server environment variables: `ZHIPU_API_KEY` and `SILICONFLOW_API_KEY`. See [.env.example](.env.example). Never put keys in browser code or Git. Existing provider restrictions, persistent quotas, authentication, and confirmation checks apply equally to both languages.

Before a chat request, you must consent to sending the question, conversation context, and relevant learning data to the listed model providers. Account credentials are excluded. AI suggestions may be wrong; no change is applied merely because you say “confirm” in chat.

## Verification and translations

```powershell
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Tests use disposable accounts and mocked model responses. PostgreSQL integration tests require a separate test database and otherwise report a skip.

UI translations live in `public/i18n.js`; server error translations live in `studypilot/i18n.py`. Translate explicit interface strings only. Keep user text, stored enum values, request authorization, and confirmation logic unchanged.


## Planning and actual study

The weekly scheduler uses your time budget, daily availability, due dates, priorities, maximum session length, and device requirements. It accounts for actual time and relevant sessions reserved in other saved weeks. Review the proposed sessions and any unscheduled work before confirming a plan.

Task status, estimated time, scheduled sessions, and actual study records are separate. Only actual study records count toward study-time statistics. Deleting a task keeps its existing study records.

## Proposal lifecycle

AI can inspect data through read-only tools and prepare supported changes as proposals. Review the proposed values, select the confirmation checkbox, and submit the card to apply a change. The server rechecks ownership, data versions, and business rules. Proposals expire after 30 minutes, and execution receipts prevent duplicate application.

Conversation messages clear on refresh or sign-out. Pending proposals and execution records persist with the account. Different deployments do not automatically synchronize data; exporting learning data does not currently provide a one-click full-account restore through the Web interface.
