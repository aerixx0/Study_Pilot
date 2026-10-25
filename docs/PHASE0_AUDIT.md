# Phase 0 audit — 2026-10-25

Baseline: `main`, commit `5e92d52`. Working tree contains two pre-existing untracked files, `Configure-AI.cmd` and `configure_ai.py`; neither is part of this work. The maintained checkout is `D:\StudyPilot`. Application paths below are relative to `python-ai-agent-ai-agent-studypilot/outputs/StudyPilot/`.

## Architecture and verified baseline

- FastAPI with native HTML/CSS/JavaScript, not Next.js, React, or Vite. A separate Chinese Streamlit interface remains available.
- SQLite for explicit local mode; PostgreSQL for deployment, with per-account schemas and shared business methods. Production does not silently use temporary SQLite.
- Server-only fixed Zhipu `glm-4.7-flash` and SiliconFlow `XingChenAGI/Xing4.0-29B` adapters using `/chat/completions`. Mock tests verify eligible fallback, not current provider availability, pricing, or commercial eligibility. No real provider request was made.
- Existing user ownership checks, scrypt password hashes, recovery codes, session/CSRF checks, quotas, export, optimistic versions, and atomic proposal receipts are implemented.
- The scheduler already enforces weekly/day/session budgets, task deadlines and computer availability, deducts actual study time and other saved reservations, and reports unscheduled work. Save recomputes the preview and rejects stale or tampered content.
- AI cannot submit arbitrary schedules or execute write tools. It can stage proposals; execution needs a separate, explicit user confirmation.
- `python -m unittest discover -s tests -v`: **165 tests, 151 passed, 14 skipped**, 135.267 seconds. Skipped tests require a separately configured local PostgreSQL test database. Model scenarios use mocks.

## Findings and priorities

| Priority | Finding and code evidence | User impact | Phase 1 response |
| --- | --- | --- | --- |
| P0 | `web.py:create_task/record` call insert methods without persistent request deduplication; `database.py:create_task/log_session` insert each time. A temporary-account reproduction returned two tasks for two identical requests with the same key. | A lost response or retry can duplicate tasks and actual minutes. Proposal execution is already idempotent, but direct forms are not. | Add account-scoped transactional receipts for keyed task/record creation, keep the same browser key until the operation completes, and test concurrency and rollback. |
| P0 | `models.py:StudyProfile` has no target deadline; `scheduler.py:generate_schedule` considers only task due dates. | A plan can satisfy individual task dates while extending past the learner's overall target. | Add an optional JSON profile field with an empty default; bound scheduling by the earlier deadline and explain conflicts. Preserve old profiles and blank goals. |
| P0 UX | `public/study.js:overview/profile/plan` presents separate pages without a first-use checklist or a confirmed-plan next action; plan preview lacks an explicit discard action. | New learners must infer the sequence and cannot easily identify their next scheduled step. | Reuse existing forms and navigation for a checklist, show the next real saved-plan action, and add a discard button. No new UI framework or fake example records. |
| P0 UX | Scheduler unscheduled items expose a reason but no adjustment suggestion. | Learners know a plan failed but not which setting can help. | Add rule-derived suggestions for time, devices and deadlines in both interfaces. |
| P0 confirmation | During UI verification, `public/study.js:plan-preview/saveDrafts` was found to restore the old preview's checked confirmation into a new preview with the same form ID. | A changed preview could appear pre-confirmed. | Clear the confirmation draft whenever generating or discarding a preview; verify in the actual browser. |
| P0 planning | `scheduler.py:generate_schedule` deducted both actual study and the full other-week reservation for the same task/day. Reservations beyond a subsequently shortened deadline were also counted. | Remaining work could be understated or concealed. | Deduct actual time from the reservation before reserving the remaining time; ignore reservations past the effective deadline. |
| P1 | Saved plans are snapshots; Web UI does not prominently flag changes to source tasks/profile/records. Streamlit does (`schedule_ui.py`). | A learner can mistake an old saved snapshot for a refreshed plan. | Show a clear snapshot notice now; advanced rescheduling/undo remains later work. |
| P1 | `TaskInput` has notes and three statuses, but no structured completion criteria, partial-completion workflow, or full-account import. | Task execution and recovery remain limited. | Document; do not introduce task-schema migrations in Phase 1. |
| P2 | `progress.py` measures actual time and current task status; no knowledge-point quiz, mastery model or review engine exists. | Time spent cannot establish mastery. | Document as planned; never invent mastery metrics. |
| Engineering | No repository CI/type-check/lint/build configuration was found. Python tests exist; Web assets are plain scripts. | Regressions rely on manual test execution. | Add a minimal test/syntax-check CI workflow. Do not introduce a bundler or type framework. |
| Documentation | Root README covers real features and install commands, but lacks a clear implemented/planned table, a phase report and clean-environment validation evidence. Windows package is a frozen preview using the separate Chinese interface. | Readers may confuse roadmap features, current source, hosted deployment and the downloadable preview. | Update only affected documentation and distinguish these versions. |

## Data and security boundaries

- No destructive migration is necessary for Phase 1. The optional deadline fits existing profile JSON; the request-receipt table is additive in both database implementations. Existing tables, accounts, tasks and records must remain intact.
- `proposals.py:execute_proposal` already combines the business write and receipt in one transaction. Existing tests cover rejection, expiry, account isolation, concurrent confirmation and receipt failure rollback; retain these paths.
- Export is not a restore mechanism. Local backup is the account-data directory; PostgreSQL backup/restore is an operator/provider responsibility. Local and hosted installations have separate data; accounts on the same hosted database share that database across browsers after login.
- Browser drafts and chat are currently memory-only, cleared by refresh/sign-out. Failure handling must retain them during a request retry; persistent chat recovery is outside Phase 1.
- Provider errors are sanitized and logs contain provider/model/status/duration. No keys, connection strings or real user data were read or written during this audit.
- The current scope does not justify a database replacement, a new account system, paid services, or a new framework.

## UI verification scope

Source inspection confirms responsive rules, reduced-motion support, focus styling and server validation. Source inspection alone does not establish mobile usability. Phase 1 acceptance will exercise a temporary account at desktop and narrow viewport sizes, including English, error/confirmation states and keyboard navigation. Screenshots, if retained, must show only test data and represent the actual application.

## Phase 1 acceptance

1. Old profile JSON loads unchanged; goals remain blank unless the user saves a change.
2. Feasible schedules satisfy day/week/session/device/task/target constraints; infeasible plans provide a reason and an adjustment, never extra capacity.
3. Rejected or unconfirmed proposals do not change business data; concurrent/repeated confirmations keep one receipt.
4. Same-key task/record retries produce one write, different payloads with the same key conflict, and write/receipt failure rolls back both.
5. AI timeout/rate-limit/invalid-output scenarios remain mocked and preserve user input; configured-provider behavior remains unchanged.
6. New users see setup → tasks → preview/confirm → next action. Preview cancellation does not save a plan.
7. Run the complete suite, JavaScript syntax checks, clean Web installation and actual UI checks. Report skipped or unexecuted items explicitly.
