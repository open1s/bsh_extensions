---
description: What LLM Sniffer captures and how captures are bounded
paths: extension.toml, **/extension.toml, docs/design.md
---

LLM Sniffer (com.open1s.llmsniff) captures LLM API traffic the BSH host mediates, through the observe hooks `http.exchange`, `model.request` and `model.response`.

What a capture record holds:

- `http.exchange`: method, host, path, status, request/response byte sizes, content type, TTFB and total latency, error, `request_id`, request and response headers (secret header values are `[redacted]`), and request/response bodies — kept for the newest 12 exchanges, 12 KiB per side, credential-shaped strings masked, with `body_truncated` when the host cut the body at 32 KiB. Older records keep the metadata and headers and say the body was dropped.
- `model.request`: model, api mode, temperature, max tokens, prompt byte size, message count and per-role counts. Message text is not copied separately; the raw HTTP body is where the text lives. The host caps a hook value at 8 KiB, so a large request arrives as truncated JSON and the record then carries `request_document` (an honest marker) instead of the counts.
- `model.response`: response type, token usage (prompt/completion/total), response byte size, tool-call flag. Response text is not copied separately.
- `turn.start` / `turn.end`: session, input size, outcome and event count — the turn's boundaries.
- `skill.load`: which skill body was attached and its size.
- `tool.before` / `tool.after`: tool name, call id and argument/result size, including namespaced MCP tools and `load_skill`.

Tools: `captures` lists records with metadata and masked headers (bodies stripped, `has_bodies` when held); `exchange` returns one record with its headers and bodies, and lists the recent request ids when the id is unknown.

What it does not see: other processes' traffic. Capture is host-mediated only.

Storage: the newest 200 records in the extension's private storage, oldest evicted; every stored string is re-redacted and size-bounded by the plugin. Records join by `request_id`; some provider paths the host takes are untraced, so correlation gaps are possible and are reported, not guessed.
