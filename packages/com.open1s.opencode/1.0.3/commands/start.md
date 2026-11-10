---
description: Start the OpenCode Zen relay and report a free model
---

Call `relay` with action=start now with no arguments. If it reports ok, call
`relay` with action=models and include_paid false, then name the first free model for the
reader, then say the **OpenCode Zen** provider is ready. Do not claim the relay
is running when the tool returned an error; report the error instead and suggest
`relay` with action=status.