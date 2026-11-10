---
description: What LLM Sniffer captures and how captures are bounded
paths: extension.toml, **/extension.toml, docs/design.md
---

LLM Sniffer (com.open1s.llmsniff) captures LLM API traffic the BSH host mediates, through the observe hooks `http.exchange`, `model.request` and `model.response`.

What a capture record holds:

- `http.exchange`: method, host, path, status, request/response byte sizes, content type, TTFB and total latency, error, `request_id`. No headers, no bodies.
- `model.request`: model, api mode, temperature, max tokens, prompt byte size, message count and per-role counts. Message text is never stored.
- `model.response`: response type, token usage (prompt/completion/total), response byte size, tool-call flag. Response text is never stored.

What it does not see: other processes' traffic, request or response bodies, header values. Capture is host-mediated only.

Storage: the newest 200 records in the extension's private storage, oldest evicted; every stored string is re-redacted and size-bounded by the plugin. Records join by `request_id`; some provider paths the host takes are untraced, so correlation gaps are possible and are reported, not guessed.
