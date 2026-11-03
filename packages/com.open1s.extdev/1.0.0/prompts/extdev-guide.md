---
description: Extension DevKit instruction
---

This workspace can build BSH extensions with the Extension DevKit.

- Never hand-write `extension.toml` from memory: call `explain` with
  `manifest` for the envelope, or `scaffold` to start from a package that
  already validates.
- Every path argument is absolute. The extension process runs with its working
  directory set to its own package, so a relative path names the wrong tree.
- Treat `check` as the gate and `lint` as the review: do not install or
  publish a package while either reports an error.
- Write tools so their declarations match their files. The host refuses a
  declared contribution whose file is missing, and ignores a file nobody
  declared.
- When a call is denied with a capability message, ask the reader to run the
  `bsh ext grant` command in the message instead of weakening the manifest.
