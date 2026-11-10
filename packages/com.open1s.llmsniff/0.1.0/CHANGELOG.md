# Changelog

## 0.1.0 - 2026-11-06

- Revision 2: capture moved from the loopback-proxy design to the host's observe hooks (`http.exchange`, `model.request`, `model.response`); runtime migrated from `process` to `extism`.
- Plugin parses hook batches for shape only, re-redacts every string, correlates by `request_id`, and stores the newest 200 records in extension storage (oldest evicted, eviction reported).
- `captures` tool queries the redacted records; overview panel renders the newest exchanges and token totals.
- Conversation text and credential values are never persisted; enforced by leak-detecting fixture tests in `plugin/`.
- Removed the process-runtime scaffold: server.py, the describe/echo tools and the scanner commands.
