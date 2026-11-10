# Changelog

## Unreleased

- Fixed: hook payloads arrive with string values, so the `model.request` and `model.response` documents are serialized JSON text; the plugin now parses them (message counts, prompt bytes, token usage, stream byte sizes and tool-call flags) instead of silently reading them as objects and storing only the point and request id.
- Capture request/response headers (secret header values masked by the host as `[redacted]`) and bounded request/response bodies (12 KiB per side, newest 12 exchanges; older records say the body was dropped). Redaction now stops at a token-shaped boundary, so a JSON body keeps its structure after a masked credential.
- Fixed: the host's HTTP tap now reports an exchange even when the vendor stops reading at its own done marker (OpenAI's stream returns on `[DONE]`). Before this, no `http.exchange` record was written at all, so headers and bodies never reached the plugin.
- Fixed: a `model.request` whose request document the host truncated at 8 KiB is kept with a `request_document` marker instead of being dropped.
- New `exchange` tool reads one record with its stored request/response headers and bodies (defaults to the newest; an unknown id lists the recent ids). `captures` now lists metadata and masked headers only, with `has_bodies` marking exchanges whose body is still held; retention raised to the newest 12 exchanges, 12 KiB per side. The overview panel shows the newest exchange's previews and header names.

## 0.1.0 - 2026-11-06

- Revision 2: capture moved from the loopback-proxy design to the host's observe hooks (`http.exchange`, `model.request`, `model.response`); runtime migrated from `process` to `extism`.
- Plugin parses hook batches for shape only, re-redacts every string, correlates by `request_id`, and stores the newest 200 records in extension storage (oldest evicted, eviction reported).
- `captures` tool queries the redacted records; overview panel renders the newest exchanges and token totals.
- Conversation text and credential values are never persisted; enforced by leak-detecting fixture tests in `plugin/`.
- Removed the process-runtime scaffold: server.py, the describe/echo tools and the scanner commands.
