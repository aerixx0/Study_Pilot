# Phase 1 delivery — 2026-10-25

## 1. Completed scope

This phase preserves FastAPI, native browser scripts, SQLite/PostgreSQL and the separate Streamlit interface. It reuses the existing scheduler, authentication, quota, proposal and transaction code. No provider or framework was replaced, and no P1/P2 system was presented as complete.

- Added a Web first-use checklist, automatic first-profile → first-task → plan progression, an initially expanded first-task form, and an Overview card for the next actual saved-plan session. Existing values are reused. Subject settings can be expanded when needed.
- Added an optional overall goal deadline. Empty or legacy profiles preserve task-deadline behavior; an older Web client omitting the field cannot silently erase an existing deadline. Both interfaces can edit it, and AI profile proposals must validate it.
- The scheduler uses the earlier target/task deadline, keeps programmatic day/week/device/session limits, and offers actionable adjustments for unscheduled work. Lower reported foundation levels break otherwise equal priority/device ties without changing user estimates or creating mastery scores.
- Fixed double deduction of actual time and the reservation it fulfils. Saved reservations beyond a shortened target/task deadline no longer conceal remaining work.
- Fixed confirmation state being carried from an old preview into a newly generated one. Added explicit preview discard. Original saved plans remain unchanged until a valid, confirmed save succeeds.
- Added persistent account-scoped retry receipts for keyed task/record creation. Concurrent requests and lost-response retries reuse one result; a changed payload with the same key conflicts. The receipt and business write roll back together.
- Preserved the existing AI proposal confirmation/expiry/version/receipt mechanism and fixed-provider fallback. Improved English failure categories and the retained-question retry message. No real model request or provider-pricing claim was needed.
- Added focused regressions, optional dependency-free Node browser-helper tests and a minimal GitHub Actions workflow.

## 2. Changed files

Application paths are relative to `python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/`.

| Files | Change |
| --- | --- |
| `studypilot/models.py`, `scheduler.py`, `progress.py` | Optional deadline, effective deadline constraints, reservation accounting, adjustment hints, date-boundary validation. |
| `studypilot/database.py`, `postgres.py`, `web.py` | Additive request receipts, shared transactional retry path, keyed HTTP writes and optional-field preservation; serve the new browser helper. |
| `studypilot/agent.py`, `agent_tools.py`, `proposals.py` | Keep deadlines user-controlled in prompts, schema and proposal validation. Execution still uses the existing confirmed transaction. |
| `public/study.js`, `workflow.js`, `i18n.js`, `index.html`, `study.css`, `studypilot/i18n.py` | Guided steps, next action, draft/retry lifecycle, confirmation reset, discard, localized errors and small responsive styles. Existing motion/theme code is retained. |
| `app.py`, `studypilot/schedule_ui.py` | Local-interface deadline input and adjustment hints. |
| `tests/test_plan_reliability.py`, `test_web.py`, `test_scheduler.py`, `test_i18n.py`, `test_workflow.cjs` | Constraint, compatibility, duplicate request, concurrency, rollback, localization and browser-helper regression coverage. |
| `.env.example`, application `README.md` / `README.en.md` | Actual variables, local setup, current functionality and validation instructions. |
| Root `README.md` / `README.en.md`, `docs/PHASE0_AUDIT.md`, this report, `docs/screenshots/` | Source/release distinction, real UI captures, implementation status, audit evidence and remaining work. |
| Root `.github/workflows/tests.yml` | Python tests/syntax and JavaScript syntax/helper checks. PostgreSQL tests remain explicitly conditional. |

The pre-existing untracked `Configure-AI.cmd` and `configure_ai.py` are preserved and excluded. Temporary environments, demo accounts, databases, logs and offline model fixtures remain under ignored `verification/`.

## 3. Validation

### Automated checks

From the application directory, the executed checks include:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m unittest tests.test_plan_reliability tests.test_web.WebTests -v
.\.venv\Scripts\python.exe -m compileall -q studypilot app.py
node --check public/study.js
node --check public/i18n.js
node --check public/workflow.js
node --check public/motion.js
node tests/test_workflow.cjs
git -c core.whitespace=cr-at-eol diff --check
```

Final full suite: **184 tests, 167 passed, 17 skipped**, 133.544 seconds, exit code 0. Targeted tests: **26 passed**. Scheduler/reliability follow-up: **20 passed**. Browser-helper checks: **14 assertions passed**. Python compilation and all four JavaScript syntax checks passed. The whitespace check allows the existing Windows CRLF line endings.

The baseline had 165 tests: 151 passed and 14 PostgreSQL tests skipped. An intermediate full run exposed one legacy fixture that reserved a session *after* its task deadline. The fixture now uses a valid future task deadline to retain its original lifetime-time/reservation assertion; separate tests assert that out-of-deadline reservations are ignored. The corrected intermediate run had **183 tests: 166 passed, 17 skipped**. A further localization regression is included in the final run.

PostgreSQL tests require `STUDYPILOT_TEST_POSTGRES` pointing at an independent localhost database. None was configured, and neither PostgreSQL nor Docker was installed locally. These tests were **not** run against production. Real provider requests and pricing/commercial-policy verification were **not** performed; model failures use mocks.

No frontend build/type-check command exists in this stack. No such check is claimed as passed. The added CI workflow must report its own result after publication; local checks are not evidence of a completed hosted CI run.

### Clean environment and real HTTP

Created a new Python 3.12 virtual environment in ignored `verification/clean-web-env`, then installed only `requirements.txt`. Installation succeeded. Started the documented `python -m uvicorn studypilot.web:app --host 127.0.0.1 --port 8528` entry with explicit local mode and an isolated account directory. Through real HTTP, verified the homepage, health response, registration, login, task save and repeated state reads. Stopped that test server, started a new process against the same isolated directory, logged in again, and verified the single saved task remained. No existing account directory or cloud database was used.

### Actual browser checks

Used a disposable local account at `127.0.0.1:8527`, not a production account:

- English first-use checklist → profile → first task → weekly preview → explicit confirmation → today's next step.
- Unconfirmed profile save is rejected and retains the entered goals, deadline, hours and preferences.
- Generating a new preview resets an already checked confirmation. Discarding it leaves the saved version unchanged.
- A 60-minute budget and 20-minute session limit yield 20+10 minute sessions for a 30-minute task; actual time remains zero until explicitly recorded.
- At 390px, plan confirmation stays reachable and its submit button measures approximately 50px high. Keyboard Space → Tab → Enter confirms a reviewed preview. At 320px, no document-level horizontal overflow was observed.
- At desktop width 1280px, verified overview and plan layout. At mobile chat width 390px, checked no document-level overflow, sidebar open/Escape close, focus return, and the selected dark-theme state.
- Offline AI failure fixture: the question remains editable and the send button becomes usable again after the error. The fixture never calls a provider and is not included in application source.
- Real screenshots are in `docs/screenshots/`. The demo task is explicitly entered test data; zero study time is not replaced with invented activity.

## 4. Remaining limitations and release boundary

- This phase does not implement structured task completion criteria, partial completion, plan undo, knowledge quizzes, mastery estimation, adaptive scheduling, a feedback database or full-account restore.
- Saved plans remain snapshots. The UI asks users to regenerate and confirm after inputs change. The next-action card shows a saved plan, not a promise that a stale plan has been automatically rebuilt.
- Actual time is still an estimate-consumption signal for scheduling, not proof that learning is complete. No quiz or mastery score is inferred.
- Drafts, chat and browser retry keys remain in tab memory. Refresh/sign-out clears them. A deliberately new request after refresh is not the same keyed operation. Legacy API clients without keys retain their old behavior.
- The optional deadline is backward-compatible when the new application reads old JSON. After saving profiles with the new field, rolling application code back to a version unaware of it may require restoring a matching backup. Do not delete or edit live profile JSON to force a rollback.
- `request_receipts` is an additive table in SQLite and PostgreSQL. No existing rows/tables are dropped. Existing PostgreSQL deployments still need integration validation before production rollout; back up persistent data and deploy code matching its data format.
- The original Windows ZIP remains `v0.6.0-preview.1`; it has not been silently replaced. Existing website availability does not prove that this branch is deployed or that model keys/backup access work.
- No production deployment or destructive data migration is part of this phase's validation. Publication status and final test results are appended below.

Delivery branch: `codex/phase1-reliability`. The phase is submitted for review without merging into `main` or changing the production deployment. The SQL additions were reviewed and covered through the shared SQLite business paths; the 17 skipped PostgreSQL integration cases remain an explicit rollout prerequisite, not a claimed success.

## 5. README changes

Retained the clear website/Windows entry points. Added actual screenshots, an implemented/planned status table, deadline/retry/confirmation behavior, current-source versus frozen-download distinctions, accurate optional/required environment variables, test commands, contribution guidance and links to audit/results. Existing accurate setup and architecture sections were retained. README remains English. No generated illustration or secret value was added.

## 6. Next phase

First validate the additive changes against an isolated PostgreSQL instance and complete CI. Then prioritize explicit task actions/completion criteria using existing notes where possible, missed-day rescheduling with preview/confirmation, and mobile task/record interactions. Evaluate partial-completion storage and safe restore only with a concrete compatibility plan. Quizzes and review rules remain Phase 3.
