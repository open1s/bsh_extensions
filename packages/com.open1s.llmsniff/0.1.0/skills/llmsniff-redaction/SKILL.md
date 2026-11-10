---
name: llmsniff-redaction
description: Read and interpret LLM Sniffer captures safely
version: 1.0.0
---

# LLM Sniffer captures

Use this skill when the reader asks to inspect, summarize or debug the LLM API traffic captured by the LLM Sniffer extension (com.open1s.llmsniff).

## What the capture is

Host-mediated LLM traffic only, seen through the BSH observe hooks (`http.exchange`, `model.request`, `model.response`). Records hold metadata (method, host, path, status, byte sizes, latency, token usage, message counts), masked request/response headers, and bounded request/response bodies for the newest twelve exchanges. A body can contain prompt and completion text; credential-shaped strings and secret header values are masked.

## How to read captures

1. Call `captures` with a `limit` (1-100) and, when relevant, a `point` filter: rows carry metadata and headers, and `has_bodies` says the exchange still holds bodies. Read them with `exchange`, passing the row's `request_id`.
2. Report by shape first: which provider host, which path, which status codes, what latency, what token usage. Compare `request_id` across points to join transport and model views. Quote a request or response body only when the reader asks for it, and say when it is truncated.
3. If a record shows `error` or a 4xx/5xx status, name the shape of the failure; do not speculate about body contents you cannot see.
4. If a correlation gap exists (an `http.exchange` with no model-level record), say the host path was likely untraced — do not invent a cause.
5. If there are no records at all, the `hooks.observe` grant is probably missing: `bsh ext grant com.open1s.llmsniff hooks.observe`.

## Hard rules

- Never repeat a credential value or a token, even one that appears masked in a record; use the masked form or say "credential present".
- Bodies may contain conversation text. Quote only when the reader asks, keep to the stored bound, and never call a body complete: the host caps at 32 KiB, the plugin at 12 KiB, and `body_truncated` says the host cut it.
- State the scope honestly: this is not system-wide sniffing; other processes' traffic is invisible.

## Acceptance gates

- A credential value never appears in any summary, panel or report.
- Every summary states the capture scope and the retention bound (newest 200 records; bodies for the newest 5, 12 KiB per side).
- Truncation and eviction are reported, never hidden.
