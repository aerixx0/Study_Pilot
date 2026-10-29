# StudyPilot v0.6.0 Preview 2

Release preparation: October 29, 2026.

[Website](https://study-pilot-olive.vercel.app/) · [Windows release and download](https://github.com/aerixx0/Study_Pilot/releases/tag/v0.6.0-preview.2) · [Windows instructions](../Usage.md)

## Scope

This release carries the Phase 1 planning and confirmation fixes, persistent task/record retry protection, and removal of the duplicate login-username editor from account settings. Display name, avatar and bio editing remain available. See the [Phase 1 report](PHASE1_REPORT.md) for the implementation and browser checks.

The README now puts the website and Windows download first, includes a copyable PowerShell download command, explains actual features and separates planned work from current functionality. The local distribution is **Windows only**. It requires Python 3.12+ and opens the Chinese Streamlit interface in a local browser; it is not a standalone EXE. The website supports English and Chinese.

`scripts/build_windows_release.py` builds the source ZIP from a committed Git revision, rejects private/runtime paths and environment credential files, normalizes Windows launchers to CRLF and adds `START-HERE.txt`. Local data, virtual environments and untracked files are excluded. Preview 1 remains a separate fixed release.

## Executed pre-deployment checks

Commands ran in the application directory on Windows with Python 3.12:

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` | **184 passed, zero skipped**, 240.723 seconds, exit code 0. |
| PostgreSQL integration cases within that suite | **17 passed** against isolated PostgreSQL 17.11 on `127.0.0.1`; no production database was used. |
| `python -m compileall -q studypilot app.py` | Passed. |
| `node --check` for every `public/*.js` file | Passed. |
| `node tests/test_workflow.cjs` | 14 assertions passed. |
| `python -m py_compile scripts/build_windows_release.py` | Passed. |
| Clean Python 3.12 virtual environment: `pip install -r requirements-local.txt` | Passed. |

The PostgreSQL cases exercise concurrent confirmation, durable quotas, reopen/persistence, account isolation, confirmation enforcement, duplicate-write receipts and transaction rollback on failure. The disposable server was shut down after testing. Model responses were mocked; this did not consume provider quota or verify live provider access.

GitHub CI now provisions an ephemeral PostgreSQL 17 service and runs these database cases, alongside Python compilation and browser-helper checks. [CI results](https://github.com/aerixx0/Study_Pilot/actions) identify each checked commit. Packaged Windows smoke checks and publication verification are recorded on the [release page](https://github.com/aerixx0/Study_Pilot/releases/tag/v0.6.0-preview.2) after packaging.

## Data and remaining limits

- The database addition is an additive `request_receipts` table, tested for rollback and account isolation. Existing goals, tasks and records are retained; this release does not replace the database or migrate local accounts into the hosted site.
- Website and local accounts remain separate. Keep the local `data` folder when updating and use your database provider's backup facilities for the hosted instance.
- Live model calls, provider pricing/commercial terms, backup restoration and a standalone Windows installer were not validated or implemented by this release.
- Plans remain day-level snapshots requiring review and confirmation. Automatic missed-day rescheduling, knowledge quizzes and mastery analysis remain roadmap items.
