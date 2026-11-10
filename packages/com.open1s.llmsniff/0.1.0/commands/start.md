---
description: Explain what LLM Sniffer is capturing and how to read it.
---

LLM Sniffer captures the LLM API traffic the BSH host mediates, through the host's observe hooks (`http.exchange`, `model.request`, `model.response`). It is not a system-wide sniffer: traffic from other processes is invisible to it.

Call the `captures` tool to read the newest records (arguments: `limit` 1-100, optional `point` filter), and summarize them by shape — provider host, path, status, latency, byte sizes, token usage. Never repeat a credential value or conversation text; records store neither.

If every query returns zero records, the `hooks.observe` grant is probably missing. Tell the reader to run:

```
bsh ext grant com.open1s.llmsniff hooks.observe
bsh ext grant com.open1s.llmsniff extension.storage
```

Report correlation gaps honestly: records join by `request_id`, and not every provider path the host takes is traced, so some exchanges may lack a model-level counterpart.
