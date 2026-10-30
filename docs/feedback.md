# Feedback: Nebius Token Factory, Nemotron, Tavily, Nebius AI Cloud

Measured while building LogicScout on 2026-10-30. Every number below comes from the raw files in
`data/measurements/`, produced by `scripts/measure_provider.py` (re-run: `uv run python scripts/measure_provider.py [section ...]`).
Sample sizes are small (n = 3 to 10 per cell), so read latencies as indicative, not as benchmarks.
In-product figures come from the `model.call` events in `data/runs/*/events.jsonl` (6 runs, 46 calls).

## 1. What worked

- **OpenAI-compatible surface, no SDK changes.** `POST /v1/chat/completions` with `response_format: json_object`, `json_schema` (strict) and `tools` all returned HTTP 200 on all three models (`json_mode.json`, `json_schema.json`, `tool_calling.json`).
- **Structured output is reliable on a small task.** `json_object`: 10/10 valid (Nano), 10/10 (Super), 5/5 (Ultra). `json_schema`: 3/3 conformant on each model. Tool calls: 3/3 called with valid arguments on each model.
- **No reasoning leakage into `content`.** 0 of 50 `json_object`/prompt-only responses contained a `<think>` tag; reasoning is returned in a separate message field.
- **Rate-limit headers are present and useful.** Every response carries `x-ratelimit-limit/remaining/reset-requests|tokens` plus `x-ratelimit-dynamic-*` and `x-request-id` (`chat_latency.json`). `remaining-requests` counted down correctly under 5 parallel calls (`concurrency.json`).
- **Concurrency of 5 was clean** on all three models: 15/15 HTTP 200, wall time 0.77 to 1.0 s.
- **Streaming works** with `stream_options.include_usage` on all three models (15/15 streams returned a usage chunk, `stream.json`).
- **Error bodies are structured** (`error.type`, `message`, `param`, `code`) and name the offending field, e.g. `body.temperature: Input should be less than or equal to 2` (`errors.json`).
- **`/v1/models` is rich:** `context_length`, `pricing`, `per_request_limits`, `quantization`, `regions`, `supported_features`, `supported_sampling_parameters`; all three target ids are listed (`models.json`, 30 models total).
- **Long input accepted:** a ~200k-character prompt was processed as 45,021 prompt tokens in 1.47 s on Nano (`errors.json`).
- **Tavily:** `topic: news` returned `published_date` on 9/9 results; invalid parameters return 400 with the allowed values listed; `include_usage` reports credits.

## 2. Friction and defects (with repro)

### Nebius Token Factory / Nemotron

1. **Reasoning consumes `max_tokens`, and `content` becomes `null` on `finish_reason: length`.** This was the biggest real cost in LogicScout.
   Repro: `POST /chat/completions {"model":"nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B","messages":[{"role":"user","content":"Reply with exactly the word: pong"}],"max_tokens":1}` returns HTTP 200, `finish_reason: "length"`, `content: null`, `reasoning: "The"` (`errors.json`, `max_tokens_1`). Same shape for the 200k-character prompt with `max_tokens: 16`.
   In product runs with `max_tokens` 8192, **20 of 31 Ultra calls and 3 of 15 Super calls ended at exactly 8192 completion tokens**; the client then saw no JSON (`runs_model_calls.json`). Ultra: 11/31 calls ok (35%); Super: 12/15 ok (80%). Failure reasons for Ultra: 8 "no JSON object found", 6 "missing key 'questions'", 6 "missing key 'rules'"; Super: 3 "no JSON object found".
   Contrast: the same JSON task with `max_tokens: 2048` and a tiny prompt finished with `stop` in 130 to 960 completion tokens on every model. Reasoning length grows sharply with prompt complexity and is not controllable from the request.
2. **Reasoning field name differs by model.** Nano returns `reasoning`; Super returns both `reasoning` and `reasoning_content`; Ultra returns only `reasoning_content` (`chat_latency.json`, first call of each model). Client code must check both.
3. **No documented reasoning control in the model metadata.** `supported_features` is `["tools","reasoning"]` and `supported_sampling_parameters` lists no reasoning-effort or thinking-budget knob (`models.json`). There is no way to cap reasoning separately from the answer.
4. **`supported_features` omits structured output.** `json_object` and `json_schema` both work (section 1) but are not advertised in `/v1/models` (`models.json`).
5. **`json_object` mode did not measurably improve validity here.** Prompt-only JSON was also 10/10, 10/10, 5/5 valid. On this task there is no difference; a harder task would be needed to show value (not measured).
6. **Leading whitespace in `content`.** Nano returned `"\npong"` and Super `"\n\npong"` for a "reply with exactly pong" instruction; Ultra returned `"pong"` (`chat_latency.json`). Callers that compare strings must strip.
7. **Model ids are case-sensitive and inconsistently cased.** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `nvidia/nemotron-3-super-120b-a12b`, `nvidia/Nemotron-3-Ultra-550b-a55b`. Lower-casing the Ultra id returns 404 `model_not_found` (`errors.json`, `ultra_lowercased_id`). Also `nvidia/Nemotron-3_5-Lightning` has `name` "Nemotron-3.5-Lightning" (underscore vs dot) (`models.json`).
8. **Redundant `detail` field in errors.** Every error repeats the message in a top-level `detail` string with the prefix "Invalid request. Please check the parameters and try again. Details:" including 401 and 404 (`errors.json`). A 401 says `Unable authenticate` under `error.type: invalid_request_error`.
9. **Nano has a much lower rate limit.** Nano: 100 requests/min, 800,000 tokens/min. Super: 1000 rpm, 1,000,000 tpm. Ultra: 1000 rpm, 2,000,000 tpm (`models.json`, headers). With 5 parallel Nano calls `remaining-requests` fell from 100 to 95 in one burst (`concurrency.json`); a parallel scout could exhaust Nano's budget first.
10. **Usage detail is inconsistent across models.** In streaming, Super and Ultra usage includes `completion_tokens_details.reasoning_tokens` (23 and 29 in the sample); Nano's usage chunk had only prompt/completion/total (`stream.json`). Non-streaming usage for the 200k prompt had `completion_tokens_details: null`.

### Tavily

1. **`published_date` is absent for `topic: general`.** 0 of 19 basic and 0 of 24 advanced results carried it, while `topic: news` gave 9/9 (`tavily.json`). The field is not in the general-topic result schema at all (keys: url, title, content, score, raw_content, id), so a briefing cannot judge source freshness unless it uses the news topic.
2. **No usage or credit reporting by default.** `usage` is `null` unless `include_usage: true` is sent, which returns `{"credits": 1}` (`tavily.json`). The flag is easy to miss.
3. **`max_results: 999` is silently accepted** with HTTP 200 (3 results returned for query "x"); no error and no warning that the value was clamped.
4. **Advanced depth costs latency.** p50 2862 ms vs 1732 ms basic, p95 4621 vs 2062 (n = 5 each). Result counts were 24 vs 19 over 5 queries; no per-result `published_date` improvement in either.
5. Error format differs from the model API: `{"detail": {"error": "..."}}` (Tavily) vs `{"error": {...}}` (Nebius). Fine, but clients must handle both.

### Nebius AI Cloud docs (from `deploy/nebius/README.md`; not executed, no credits spent)

These are documentation observations made while writing the deployment guide, not measurements.
- The CLI install page documents Ubuntu and macOS only; Windows users need WSL or Cloud Shell.
- Platform and preset names (`cpu-d3`, `4vcpu-16gb`) vary by region and must be discovered via `nebius ai endpoint create --help` or the console.
- Serverless Endpoints and Jobs are billed per second, so a project with credits or billing is required before even a dry run is useful.
- Using a public registry avoids credential setup, but registry-auth flags then differ for private images.

## 3. Measurements

Chat latency, prompt "Reply with exactly the word: pong", `max_tokens` 512, n = 10 each, ms (`chat_latency.json`):

| Model | HTTP 200 | min | p50 | p95 | max |
|---|---|---|---|---|---|
| Nano 30B-A3B | 10/10 | 313 | 471 | 1848 | 1848 |
| Super 120B-A12B | 10/10 | 355 | 591 | 734 | 734 |
| Ultra 550B-A55B | 10/10 | 475 | 589 | 1198 | 1198 |

Streaming time to first chunk vs first content token, n = 5 each, ms (`stream.json`). First chunk arrives before content because reasoning streams first:

| Model | TTFT p50 | first-content p50 | usage chunk |
|---|---|---|---|
| Nano | 158 | 718 | 5/5 |
| Super | 440 | 535 | 5/5 |
| Ultra | 472 | 617 | 5/5 |

Structured output and features (`json_mode.json`, `json_schema.json`, `tool_calling.json`, `concurrency.json`):

| Model | json_object valid | prompt-only valid | json_schema conformant | tool call valid | `<think>` in content | json_object latency p50 (ms) | 5-parallel wall (ms) |
|---|---|---|---|---|---|---|---|
| Nano | 10/10 | 10/10 | 3/3 | 3/3 | 0 | 1151 | 1005 |
| Super | 10/10 | 10/10 | 3/3 | 3/3 | 0 | 1424 | 769 |
| Ultra | 5/5 | 5/5 | 3/3 | 3/3 | 0 | 887 | 958 |

Model metadata and rate limits (`models.json`; prices in USD per token as returned, shown per million tokens):

| Model | context | quantization | in / out $ per 1M | rpm / tpm |
|---|---|---|---|---|
| Nano | 262,144 | fp8 | 0.06 / 0.24 | 100 / 800,000 |
| Super | 262,144 | fp4 | 0.30 / 0.90 | 1000 / 1,000,000 |
| Ultra | 1,048,576 | fp4 | 1.00 / 3.00 | 1000 / 2,000,000 |

Errors (`errors.json`):

| Case | Status | Message |
|---|---|---|
| unknown model | 404 | `The model ... does not exist.` code `model_not_found` |
| missing `messages` | 422 | `body.messages: Field required` |
| temperature 9 | 422 | `Input should be less than or equal to 2` |
| max_tokens -5 | 422 | `Input should be greater than or equal to 0` |
| bad role | 422 | lists allowed roles |
| bad response_format type | 422 | lists `text`, `json_object`, `json_schema` |
| malformed JSON body | 422 | `body.1: JSON decode error` |
| bad API key | 401 | `Couldn't authenticate. Reason: Unable authenticate` |
| 45k-token prompt (Nano) | 200 | accepted, 1471 ms |

In-product `model.call` stats from real runs (`runs_model_calls.json`; 6 runs):

| Model | calls | ok | escalated flag | latency p50 / p95 (all calls, ms) | calls at 8192 completion tokens |
|---|---|---|---|---|---|
| Super (fast tier) | 15 | 12 | 0 | 13,446 / 40,862 | 3 |
| Ultra (deep tier) | 31 | 11 | 0 | 25,836 / 30,164 | 20 |

Nano was not used in product runs. Product latencies are 20 to 40 times the small-prompt latencies above because completions are thousands of reasoning tokens (median 8192 for Ultra, 2699 for Super).

Tavily (`tavily.json`, 5 queries per depth, `max_results` 5):

| Depth | p50 / p95 latency (ms) | results | with `published_date` |
|---|---|---|---|
| basic | 1732 / 2062 | 19 | 0 |
| advanced | 2862 / 4621 | 24 | 0 |
| basic, topic news (3 queries) | n/a | 9 | 9 |

## 4. Suggested improvements

**Nebius Token Factory / Nemotron**
1. Return a non-null `content` or a distinct `finish_reason` (e.g. `length_in_reasoning`) when `max_tokens` runs out during reasoning, and document it. Better: expose a reasoning budget parameter (or a `reasoning_effort` knob) so JSON callers can reserve answer tokens.
2. Use one reasoning field name across all Nemotron models and document it (`reasoning_content` on Nano is missing today).
3. Advertise `json_object` and `json_schema` in `supported_features`, and include a `max_output_tokens` per model in `/v1/models`.
4. Normalize model id casing (or accept case-insensitive ids) and keep `id` and `name` spellings consistent.
5. Always include `completion_tokens_details.reasoning_tokens` in usage, so clients can see how much of the budget reasoning used.
6. Strip the leading newline(s) from `content` after a reasoning block.
7. Raise or document the Nano 100 rpm limit relative to Super and Ultra, since it is the cheapest tier meant for high call volume.
8. Drop the duplicated `detail` field, and use `authentication_error` for 401.

**Tavily**
1. Return `published_date` (or an explicit `null`) in every result, for every topic, or document the topic dependency in the search reference.
2. Include a `usage` block (credits) in every response by default.
3. Reject or warn on out-of-range `max_results` instead of silently accepting it.

**Nebius AI Cloud docs**
1. Add a Windows or PowerShell install path for the CLI, or state WSL explicitly on the install page.
2. Provide a per-region table of valid `--platform` and `--preset` values, and a worked `--dry-run` example in the Serverless endpoint guide.
