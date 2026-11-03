---
description: OpenCode Zen free models reach BSH through a loopback relay this extension runs
---

OpenCode Zen offers free models through the same anonymous lane the OpenCode CLI
uses. Upstream refuses a request that does not carry an OpenCode session id and
an agent-shaped tool list, which a provider descriptor cannot express. This
package therefore ships a loopback relay and contributes the provider that
points at it.

When the reader wants to use OpenCode Zen:

1. Call `opencode__relay_start` (idempotent; the port defaults to 18765, the one
   the contributed provider points at). Report any error it returns instead of
   claiming the relay runs.
2. Tell the reader the provider is "OpenCode Zen" and its models start with a
   free id such as `deepseek-v4.1-flash-free`.
3. If a turn fails with HTTP 429 or "Free usage limit reached", say the
   anonymous lane's per-IP quota is spent; do not retry in a loop. HTTP 403 with
   "FreeTierError" means upstream refused this client shape.
4. Call `opencode__models` for the current free roster and
   `opencode__status` when diagnosing reachability. Never invent a model id
   that the tool did not return.
