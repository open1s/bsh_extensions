---
description: LLM Sniffer redaction and capture rules
---

LLM Sniffer (com.open1s.llmsniff) observes the LLM traffic the BSH host mediates via the `http.exchange`, `model.request` and `model.response` hooks. Read docs/design.md before changing the package.

Rules:

- Capture is host-mediated only. Never present it as system-wide sniffing, and never promise visibility into other processes.
- Never repeat a credential value, a bearer token or a full `sk-`/`ghp_` string in any output, log or record. Use the masked form or say "credential present".
- Conversation text is never persisted: describe requests by shape (roles, counts, byte sizes) and responses by usage numbers. Never quote a user message or a model answer from a capture.
- Raw bodies are not captured. If the reader asks for bodies, explain that the host hook does not deliver them and that enabling them would be a host-side design change.
- Bound everything: newest 200 records, oldest evicted; report truncation and eviction honestly.
- Correlate by `request_id`; say so when an exchange has no model-level counterpart instead of guessing.
- No network, process, workspace or secret capability may be added without a design change.
- Call validate and lint after every change, and quote their rule ids.
