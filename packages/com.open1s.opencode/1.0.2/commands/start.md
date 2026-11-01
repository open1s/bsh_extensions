---
description: Start the OpenCode Zen relay and report a free model
---

Call `opencode__relay_start` now with no arguments. If it reports ok, call
`opencode__models` with include_paid false and name the first free model for the
reader, then say the **OpenCode Zen** provider is ready. Do not claim the relay
is running when the tool returned an error; report the error instead and suggest
`opencode__status`.
