# Cloudflare Workers AI setup

StudyPilot keeps its existing FastAPI application, Vercel hosting and database. Cloudflare is an additional model service, not a hosting migration. No database migration is required.

## Routing and free usage

Priority is **Zhipu → Cloudflare → SiliconFlow**. Each conversation selects the first **two** fully configured providers, not all three. A failed provider is not revisited in later tool rounds. With only Zhipu configured, the existing one-extra-attempt policy for known transient Zhipu errors remains. With a backup configured, the adapter tries it immediately on eligible transient failures.

The Cloudflare model is fixed to `@cf/zai-org/glm-4.7-flash`. No browser-supplied model, account ID or Base URL is accepted. Account IDs must be 32 hexadecimal characters. Redirects are disabled. Calls are non-streaming and share the existing request deadline; output is validated before display or tool dispatch.

Use **Workers Free**, not Workers Paid or prepaid AI Gateway credits. Cloudflare currently provides 10,000 Neurons per UTC day and stops Free-plan requests at the limit. Neurons measure compute, not a fixed number of messages. The same model can incur overage charges on a paid account; StudyPilot does not change or verify the external billing plan. There is no automatic account upgrade, credit purchase, or paid-model substitution.

## Configure Production on Vercel

1. Sign in to your own [Cloudflare dashboard](https://dash.cloudflare.com/). Keep the account on Workers Free.
2. Open **Workers AI → Use REST API**. Copy the **Account ID**.
3. Create the **Workers AI API Token** using the provided template. Restrict it to the intended account. Official instructions require Workers AI Read and Edit permissions; do not use a Global API Key or grant DNS/account-administration permissions.
4. In the StudyPilot Vercel project, open **Settings → Environment Variables**. Add **Production only**:
   - `CLOUDFLARE_ACCOUNT_ID`: the account ID.
   - `CLOUDFLARE_API_TOKEN`: the token, stored as a Secret/Sensitive variable.
5. Redeploy the latest production deployment after saving variables. Existing deployments do not acquire changed environment variables automatically.
6. Reload StudyPilot. The developer-only maintenance screen shows whether both values are configured. It never shows the token. A live chat request is still needed to verify permissions and capacity.

Keep `ZHIPU_API_KEY` to use Zhipu first. If only Cloudflare is configured, it becomes the sole/first provider. Existing SiliconFlow-only installations still work. Do not send tokens through chat, commit them, or place them in browser code. Remove/rotate a compromised token in Cloudflare, then update Vercel and redeploy.

## Local Windows source checkout

Set both variables in the **server process environment**, then restart the local application. StudyPilot does not automatically load `.env` files. Keep real values out of shell history by using private input or your environment manager rather than pasting a token into a command. `.env.example` documents names only. Website and local accounts remain separate; this change does not synchronize data.

The published Preview 2 ZIP is an older, fixed snapshot and does not include this adapter. Use a current source checkout for local Cloudflare support until a newer Windows release is published.

## Data and confirmation

Cloudflare is an overseas provider. After consent, questions, conversation context and relevant learning data may be sent to the selected providers. Account credentials are excluded. Cloudflare states that Workers AI customer content is not used for training; standard inference retention has limited exceptions, and enabling logging, caching or stateful features may store content. Review its policy for your deployment and audience.

All three existing modes (`chat`, `goal_coach`, `plan_builder`) keep the same bounded tool loop. Only read tools and staged modification proposals are available to models. Applying changes still requires explicit user confirmation and server-side ownership, schema and version checks. A failed request does not execute its pending proposals.

## Troubleshooting

| Status | Meaning and action |
| --- | --- |
| Not configured | Token or valid Account ID is missing. Check Production scope and redeploy. |
| HTTP 401/403 | Check the token, account scope and Workers AI permissions; no automatic retry. |
| Code 3036 | Daily free allowance exhausted; wait for the next UTC day. No paid upgrade is attempted. |
| Code 3040 | Model capacity is temporarily unavailable; an eligible already-selected backup may be tried. |
| Code 5035 | Provider now requires paid access; stop and review availability. The app will not upgrade or choose a different model. |
| Timeout/network/server error | The selected backup may be tried within the same deadline. Inputs remain in the open tab. |
| Invalid/truncated model output | Rejected; no protected write is applied. |

Logs contain only provider/model, latency, normalized outcome, HTTP status and allowlisted error codes. Do not enable logging of request bodies, authorization headers or user learning data.

## Validation

From the application directory:

```powershell
python -m unittest discover -s tests -p test_cloudflare_ai.py -v
python -m unittest discover -s tests -v
python -m compileall -q studypilot app.py
node tests/test_workflow.cjs
node --check public/study.js
node --check public/i18n.js
```

Model calls are mocked. PostgreSQL integration cases require an isolated localhost test database through `STUDYPILOT_TEST_POSTGRES`; CI provisions one. Mock success is not evidence of live account availability.

## Official references

- [OpenAI-compatible endpoint](https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/)
- [Token and Account ID setup](https://developers.cloudflare.com/workers-ai/get-started/rest-api/)
- [GLM-4.7-Flash model and tool support](https://developers.cloudflare.com/workers-ai/models/glm-4.7-flash/)
- [Free-plan eligible models](https://developers.cloudflare.com/changelog/post/2026-07-28-models-require-workers-paid/)
- [Pricing and limits](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- [Error codes](https://developers.cloudflare.com/workers-ai/platform/errors/)
- [Data policy](https://developers.cloudflare.com/workers-ai/platform/data-usage/)
