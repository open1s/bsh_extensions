# Extension design: LLM Sniffer (revision 2 — host hook, no proxy)

> Observe the HTTP JSON traffic the BSH host exchanges with LLM provider APIs through the host's `http.exchange` observe hook, parse it generically, and redact credentials before anything is stored or shown.

Id: `com.open1s.llmsniff`  |  Version: 0.1.0 (unreleased)  |  Runtime: `extism`

Revision 2 supersedes the loopback-proxy design and the earlier security-scanner scaffold text. The reader directed the capture to use a host hook instead of a proxy. There is no `http.tap` hook point in this host; the declared hook points are `model.request`, `model.response`, `tool.before`, `tool.after` and `http.exchange` (devkit/constants.py `HOOK_POINTS`). `http.exchange` is the seam this design uses.

This is a proposal. Nothing in the package changes until the reader confirms the id, runtime and surface below.

## Why the runtime must be extism

The validator enforces it, and it is not negotiable in this build:

- `contribution.hook` — "observe hooks are delivered by the extism runtime in this build" (validate.py:566) errors for any other runtime when a `hook` contribution is declared.
- `capabilities.hooks` — observe hooks require `hooks.observe` in `capabilities.required` (validate.py:432).
- `runtime.entry` — the extism entry must be a package-relative `.wasm` file (validate.py:386).

A hook contribution is declaration-only (no file, constants.py:113); the plugin is the runtime entry. The wasm sandbox is also a safety improvement over the proxy design: the plugin cannot open sockets, so capture cannot exfiltrate unless the host grants a network capability, which this design does not request.

Honest scope statement: a host hook sees only traffic the host mediates. It does not see other processes' traffic the way a system proxy or pcap would. If system-wide capture is the actual requirement, this design is the wrong tool and the proxy conversation should be reopened.

## Domain fit

| Field | Value |
|---|---|
| Domain | security |
| Confidence | high |
| Matched signals | capture, parse, redact, secrets, traffic |
| Runtime | extism (forced by the hook delivery rule above) |
| Why | The package observes host seams and must redact before storage; it executes no processes and opens no sockets. |

## Spike answers (from host source, no spike build needed)

All three blocking unknowns were resolved by reading the host implementation (`bos` repo) and the shipped example `examples/extensions/extism-hook`:

1. **Export and payload.** The host calls the guest export `bsh_hook` with one JSON string `{"point": "...", "batch": [event, ...]}` (ferris-runtime/src/extism.rs:961); the plugin returns `{"action": "continue"}`. For `http.exchange` each event carries `{source, request_id, method, host, path, status, request_bytes, response_bytes, content_type, ttfb_ms, total_ms, error, request_headers, response_headers, request_body, response_body, body_truncated}` (ferris-runtime/src/hooks.rs:139-214). The tap masks credential header values as `[redacted]` and caps each body at 32 KiB (react/src/llm/vendor/tap.rs:22-42); the host re-redacts every string through `redact`/`redact_payload` before dispatch.
2. **Model-level view.** The host's hook context is a `HashMap<String, String>` (agent/src/agent/hooks.rs:104), so every value under `data` is a string and a nested document arrives serialized. `model.request` carries `{agent, data: {model, request_id, request}}` where `request` is the JSON text `{request_id, model, api_mode, temperature, max_tokens, prompt_bytes, messages}` (agent/src/agent/context.rs:1270-1282); `model.response` carries either `response` (the react document `{response_type, usage}`) or, for a streamed step, `response_bytes`, `response_text` and `had_tool_call` directly on `data` (context.rs:1284-1295, 1398-1422). The plugin parses those strings (`object`/`number`/`boolean` in plugin/src/lib.rs) before reading shape. The host caps a hook value at 8 KiB, so a large `request` document arrives truncated: the record is kept with a `request_document` marker instead of the counts (the raw body is on the exchange). `data.request.messages` and `response_text` contain conversation text (host-redacted string-wise, but present): the plugin must parse shape only — counts and byte sizes — and never persist them.
3. **Storage and tools.** Extism plugins get private KV through the `bsh_host` function with ops `storage_get`/`storage_set`, gated by the `extension.storage` capability (low risk, devkit/constants.py:61), and can expose tools via `bsh_tools`/`bsh_call_tool`. Both are proven by the working `extism-hook` example. Toolchain confirmed: cargo 1.98.1 with `wasm32-unknown-unknown` installed.

Consequence: capture correlates `http.exchange` with `model.request`/`model.response` by `request_id`, stores redacted records in extension storage, and can offer a query tool. The design ships all three hook points plus one `captures` tool.

## Contributions

| Kind | Id | File | Capability | Purpose |
|---|---|---|---|---|
| hook | http.exchange | — (declaration only) | hooks.observe | Transport view: method, host, path, status, bytes, latency, masked headers and bounded bodies per LLM call. |
| hook | model.request | — (declaration only) | hooks.observe | Request view: model, api_mode, prompt size; messages parsed for shape, the raw body comes from the exchange. |
| hook | model.response | — (declaration only) | hooks.observe | Response view: token usage per request_id; the raw body comes from the exchange. |
| tool | captures | — (bsh_tools/bsh_call_tool) | agent.tools.register | List the last N redacted records with metadata and headers, optional point filter. |
| tool | exchange | — (bsh_tools/bsh_call_tool) | agent.tools.register | Read one exchange with its stored headers and bodies. |
| command | start | commands/start.md (exists) | ui.commands | Explain what capture is running and how to read it. |
| prompt | rules | prompts/rules.md (rewrite) | agent.prompts.provide | Never repeat a credential; describe exchanges by shape. |
| context | llm-traffic | contexts/security.md → contexts/llm-traffic.md (rename + rewrite) | agent.context.provide | What is captured, what is redacted, retention bounds. |
| skill | llmsniff-redaction | skills/llmsniff-redaction/SKILL.md (rewrite) | agent.skills.provide | Read captures safely; escalate only shapes, never values. |
| panel | overview | panels/overview.json (rewrite) | ui.panels | Last N redacted exchanges plus the newest exchange's request/response previews, status, latency and token counts. |

Removed from the scaffold (scanner leftovers and process-runtime artifacts): `tools/describe.json`, `tools/echo.json`, `server.py`, `commands/run-scan.md`, `commands/write-report.md`, and capabilities `process.execute`.

## Tool surface

Two tools, both implemented through the plugin's `bsh_tools`/`bsh_call_tool` exports (as proven by the extism-hook example):

- `captures` — `{limit?: int <= 100, point?: "http.exchange" | "model.request" | "model.response"}`; returns the newest records newest first, each with metadata and masked headers (bodies stripped, `has_bodies` when the exchange still holds them), plus the stored and eviction counts.
- `exchange` — `{request_id?: string, include_headers?: bool}`; returns one `http.exchange` record with its stored request/response headers and bodies, defaulting to the newest exchange; an unknown id lists the recent ids.

## Capabilities and grants

| Capability | Risk | Why this package needs it | Grant |
|---|---|---|---|
| hooks.observe | high | receives observe-hook batches from the host seam | bsh ext grant com.open1s.llmsniff hooks.observe |
| extension.storage | low | private KV for redacted capture records | bsh ext grant com.open1s.llmsniff extension.storage |
| agent.tools.register | low | exposes the captures and exchange tools | automatic |
| ui.commands | low | adds /start | automatic for community packages |
| agent.prompts.provide | low | supplies the redaction rules | automatic |
| agent.context.provide | low | adds the capture conventions | automatic |
| agent.skills.provide | low | ships the safe-reading workflow | automatic |
| ui.panels | low | adds the capture overview panel | automatic |

`hooks.observe` is high risk: declaring it in the manifest is a request, not an authorization. Without this explicit grant the hook never fires.

```text
bsh ext grant com.open1s.llmsniff hooks.observe
bsh ext grant com.open1s.llmsniff extension.storage
```

Deliberately not requested: `network.http`, `process.execute`, `workspace.*`, `secrets.read`. The wasm runtime cannot use them anyway; their absence is the design's main safety property.

## Safety rules

- Redact before storage: `Authorization`, `x-api-key`, `api-key`, `cookie`, any bearer/`sk-`-shaped token in headers or bodies. Store presence and a stable fingerprint, never the value.
- Conversation text reaches storage only as part of a captured body: `http.exchange` keeps request/response bodies for the newest 12 exchanges, 12 KiB per side, re-redacted; `model.request` messages are counted and sized, `model.response` text is not copied separately.
- Bodies are bounded twice: the host cuts at 32 KiB (`body_truncated`), the plugin keeps 12 KiB per side and says when it cut. Older records keep metadata and headers and report that the body was dropped.
- Bound everything: record count, record bytes, panel rows. Report truncation honestly.
- No network egress: the plugin declares no network capability and the runtime cannot open sockets.
- Capture is host-mediated traffic only; the panel and context must say so, so nobody mistakes this for system-wide sniffing.

## Build order

1. Migrate `extension.toml`: runtime `extism`, entry `plugin.wasm`, hooks `http.exchange` + `model.request` + `model.response`, tool `captures`, capabilities per the table above; delete the process-runtime artifacts and scanner leftovers.
2. `plugin/` crate (extism-pdk 1.4, cdylib, `wasm32-unknown-unknown`) → `plugin.wasm`: `bsh_hook` correlates by `request_id`, redacts, stores bounded records; `bsh_tools`/`bsh_call_tool` serve `captures`; `bsh_panel` renders the overview. Fixture tests with fake `sk-` keys that fail if a value leaks.
3. Rewrite the text contributions and the panel for capture reading.
4. `validate` → `lint` → `check --smoke` as the release gate; quote rule ids for anything that fails.
5. Install, then `bsh ext grant com.open1s.llmsniff hooks.observe` and `bsh ext grant com.open1s.llmsniff extension.storage` — without the first the hook never fires.

## Acceptance gates

- [x] A fake `sk-…` key in a fixture never appears in any stored record, panel or log (plugin tests: `redact_masks_markers`, `model_request_record_never_stores_message_text`, `model_response_record_never_stores_response_text`).
- [x] Records are bounded (count and bytes) and truncation is reported (plugin tests: `store_bound_evicts_oldest`, `oversized_record_is_reduced_with_marker`, `bound_string_caps_long_values`).
- [x] No network, process, workspace or secret capability is declared (validate: 0 errors).
- [x] The panel shows provider, model, status, latency and token counts for the last N exchanges, redacted (bsh_panel export; `bsh ext mock` renders the card).
- [x] `validate`, `lint` and `check --smoke` all pass; the manifest ships every file it declares (check hash eb1c3c25…, 18 files; smoke note: extism cannot be smoke-tested locally, `bsh ext mock captures` exercised instead).

## Open questions

1. Confirm the scope cut: host-mediated LLM traffic only. If system-wide capture is the real requirement, stop here and reopen the proxy design.
2. Confirm the `captures` tool and the three hook points (`http.exchange`, `model.request`, `model.response`) — or trim to `http.exchange` only.
3. Retention: how much capture history is useful — last session, last N exchanges, or a bounded log file? Default proposal: keep the newest 200 records in extension storage, evict oldest.

## Existing package check

The scaffold exists at `/Users/gaosg/Projects/bsh_extensions/packages/com.open1s.llmsniff/0.1.0` with process-runtime artifacts and scanner leftovers. The migration to this design touches: `extension.toml` (runtime, capabilities, contributions), deletions listed above, rewrites of the five text contributions, and a new `plugin/` crate building `plugin.wasm`. None of that starts before the reader confirms this blueprint.

## Next

- Reader confirms or changes: runtime `extism`, the three hook points, the `captures` tool, retention 200 records, id `com.open1s.llmsniff`.
- bsh ext grant com.open1s.llmsniff hooks.observe
- bsh ext grant com.open1s.llmsniff extension.storage

## Implementation checklist

- [x] A validating manifest 2.0 skeleton exists (still process-shaped; revision pending confirmation).
- [x] Spike: payload shape and export name recorded above (from host source + extism-hook example).
- [x] Migrate `extension.toml` to runtime `extism`, entry `plugin.wasm`, hooks + tool + capabilities per this revision.
- [x] Remove `server.py`, `tools/describe.json`, `tools/echo.json`, `commands/run-scan.md`, `commands/write-report.md` and their declarations.
- [x] Plugin: parse + redact + correlate, with leak-detecting fixture tests (9 tests green).
- [x] `captures` tool and `bsh_panel` overview over extension storage.
- [x] Rewrite commands/start.md, prompts/rules.md, contexts/llm-traffic.md, skills/llmsniff-redaction/SKILL.md, panels/overview.json.
- [x] `validate` → `lint` → `check --smoke` green; gates above ticked.

Generated by the Extension DevKit workflow, revised by hand for the hook-based design on 2026-11-05.
