# Cloudflare adapter validation

Validated on Windows with Python 3.12 on 2026-10-31.

## Scope

- Added the fixed Cloudflare Workers AI GLM-4.7-Flash endpoint to the existing server adapter.
- Preserved Zhipu priority and the existing SiliconFlow fallback when Cloudflare is absent.
- Limited each conversation, including all tool rounds, to two configured providers.
- Added Account ID validation, safe Cloudflare error categories, developer-only configuration status and English/Chinese disclosures listing configured providers.
- Kept authentication, persistent quotas, proposal confirmation, ownership/version validation and database schemas unchanged.
- Added setup, privacy, free-plan and deployment documentation. No additional dependency or framework was introduced.

## Executed checks

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -p test_cloudflare_ai.py -v` | 10 passed; mocked HTTP, no real model quota. |
| `python -m unittest discover -s tests -v` with isolated PostgreSQL 17.11 | 204 passed, zero skips, 191.120 seconds. PostgreSQL stopped afterward. |
| `python -m compileall -q studypilot app.py` | Passed. |
| `node tests/test_workflow.cjs` | Passed, 14 assertions. |
| `node --check` for every `public/*.js` file | Passed. |
| `git diff --check` | Passed. |

Mock cases cover a successful Cloudflare call, Zhipu 429/timeout/server failure recovery, three configured providers never reaching the third, Cloudflare-to-SiliconFlow recovery, missing/invalid Account IDs, daily free quota/paid access/capacity errors, invalid output, confirmation and duplicate execution, authenticated configuration status, consent and persistent per-user quota.

A browser check with an isolated local developer account verified the configuration table, platform links and English/Chinese conversation disclosures. A final presentation-only correction translated provider labels in English; JavaScript syntax and the workflow checks were rerun afterward.

The first targeted run exposed two errors in the new test fixtures (incorrect tool name and missing test-role confirmation). Those fixtures were corrected before the successful targeted and full runs. No production bypass was introduced.

## Live configuration checks

With owner approval, a Token restricted to the intended account's Workers AI Read/Edit permissions and its Account ID were stored as Vercel Production Secrets. No credential values were written into source, this report or test logs.

One direct server-adapter connection check against Cloudflare returned a usable reply in 13.58 seconds. The test used a fixed connection prompt, no user learning data and no tools. The Cloudflare dashboard showed **Free / $0 / Current plan**. This point-in-time check is not an uptime or latency guarantee. Production deployment validation is separate from this direct adapter check.

## Limits

Keep Cloudflare on Workers Free. An externally upgraded paid account may incur overage charges, and the app cannot enforce the external billing plan. New credentials or quota policies require a fresh production deployment. The frozen Windows Preview 2 download predates this adapter; local Cloudflare support requires the current source checkout until a new release is published.
