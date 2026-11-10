---
description: LLM Sniffer redaction and capture rules
---

LLM Sniffer (com.open1s.llmsniff) observes the LLM traffic the BSH host mediates via the `http.exchange`, `model.request` and `model.response` hooks. Read docs/design.md before changing the package.

Rules:

- Capture is host-mediated only. Never present it as system-wide sniffing, and never promise visibility into other processes.
- Never repeat a credential value, a bearer token or a full `sk-`/`ghp_` string in any output, log or record. Use the masked form or say "credential present".
- Bodies are captured: the newest 12 exchanges keep up to 12 KiB per side, re-redacted. A body can contain prompt and completion text, so treat captures as sensitive; quote one only when the reader asks, and say when it is truncated (`body_truncated`, or the stored bound).
- Credential-shaped strings (`sk-`, `ghp_`, `Bearer`) and secret header values are masked before storage. Never repeat a credential even if a capture appears to show one.
- Bound everything: newest 200 records, oldest evicted; report truncation and eviction honestly.
- Correlate by `request_id`; say so when an exchange has no model-level counterpart instead of guessing.
- No network, process, workspace or secret capability may be added without a design change.
- Call validate and lint after every change, and quote their rule ids.
