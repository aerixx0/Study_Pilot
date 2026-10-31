# AI rate limits and recovery

A working key does not guarantee every request will succeed. The hosted service has returned both successful GLM replies and HTTP 429 responses. The original adapter classified every HTTP 429 as a rate limit and discarded the provider's business code, so those old logs cannot distinguish account limits from platform overload.

## Source behavior

- The provider/model allowlist is unchanged: GLM-4.7-Flash first; SiliconFlow's configured Xing4.0-29B fallback. Keys remain server environment variables.
- When a backup key is configured, eligible transient failures use the existing fallback immediately, without an added retry of GLM.
- With only GLM configured, recognized transient business codes `1302` (account rate limit) and `1305` (model overload) can trigger **one extra attempt per chat run**, shared across all tool rounds. This retries a model request, not the whole agent or any data modification.
- The delay respects `Retry-After` seconds or an HTTP date. Otherwise it waits 2–2.5 seconds with jitter. It skips the extra attempt if the original request deadline cannot accommodate the wait and a response. The wait does not extend the existing time budget.
- Unclassified 429 responses, account quota/balance restrictions, permission errors, invalid output and timeouts do not trigger this same-provider retry. Existing eligible free-provider fallback remains available.
- Only allowlisted numeric business codes are logged, alongside provider, model, HTTP status, outcome and duration. Upstream error text, prompts, credentials and learning data are excluded. Error bodies are bounded to 4 KiB.
- User messages distinguish model overload, account quota/balance restrictions and access restrictions. English translations use the same fixed categories.

These controls cannot increase the provider account's limits or eliminate a platform outage. There is no new cross-instance global request queue; the existing account/site request quotas remain in force. API users can view their actual model concurrency allowance in the provider console.

## Provider references

- [Zhipu rate-limit guidance](https://docs.bigmodel.cn/cn/api/rate-limit): account/model concurrency limits, codes 1302/1305, and avoiding immediate repeated requests.
- [Zhipu business error codes](https://docs.bigmodel.cn/cn/api/api-code): HTTP 429 also covers account balance, usage and access restrictions; it is not sufficient to identify the cause by itself.

## Verification

Tests use mocked HTTP responses and clocks; they make no real provider calls. The recovery tests cover transient recovery, a strict single extra attempt across tool rounds, fallback, deadline exhaustion, `Retry-After`, quota/access errors, malformed/oversized bodies and secret-free logs.

From the application directory:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_free_ai tests.test_agent tests.test_i18n -v
```

Check the deployed commit before assuming a hosted instance includes this source change. A proposed change is not a completed production release.
