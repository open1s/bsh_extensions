---
name: llmsniff-redaction
description: Read and interpret LLM Sniffer captures safely
version: 1.0.0
---

# LLM Sniffer captures

Use this skill when the reader asks to inspect, summarize or debug the LLM API traffic captured by the LLM Sniffer extension (com.open1s.llmsniff).

## What the capture is

Host-mediated LLM traffic only, seen through the BSH observe hooks (`http.exchange`, `model.request`, `model.response`). Records hold metadata and redacted previews: method, host, path, status, byte sizes, latency, token usage, message counts. They never hold request or response bodies, header values, conversation text or credential values.

## How to read captures

1. Call the `captures` tool with a `limit` (1-100) and, when relevant, a `point` filter.
2. Report by shape: which provider host, which path, which status codes, what latency, what token usage. Compare `request_id` across points to join transport and model views.
3. If a record shows `error` or a 4xx/5xx status, name the shape of the failure; do not speculate about body contents you cannot see.
4. If a correlation gap exists (an `http.exchange` with no model-level record), say the host path was likely untraced — do not invent a cause.
5. If there are no records at all, the `hooks.observe` grant is probably missing: `bsh ext grant com.open1s.llmsniff hooks.observe`.

## Hard rules

- Never repeat a credential value or a token, even one that appears masked in a record; use the masked form or say "credential present".
- Never quote conversation text; it is not in the records, and reconstructing it from previews is forbidden.
- State the scope honestly: this is not system-wide sniffing; other processes' traffic is invisible.

## Acceptance gates

- A credential value never appears in any summary, panel or report.
- Every summary states the capture scope and the retention bound (newest 200 records).
- Truncation and eviction are reported, never hidden.
