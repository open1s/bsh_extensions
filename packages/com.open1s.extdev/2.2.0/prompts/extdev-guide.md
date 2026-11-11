---
description: Extension DevKit instruction
---

This workspace can design, build and ship BSH extensions with the Extension
DevKit.

- For a new extension for a specific domain, load the extdev-design skill and
  call design before writing a manifest. A domain package starts from a
  blueprint; scaffold, do not hand-write extension.toml.
- The domain catalogue is knowledge, devops, data, web, documents, media,
  messaging, security, research, model, system and generic. Name the work,
  not the technology.
- After scaffold, docs/design.md is the build plan. Work one unchecked item
  at a time, then call validate, lint and smoke. Keep the manifest and the
  contribution files in the same change.
- Every path argument is absolute. The extension process runs with its
  working directory set to its own package, so a relative path names the
  wrong tree.
- Treat check as the gate and lint as the review: do not install or publish a
  package while either reports an error.
- Write tools so their declarations match their files. The host refuses a
  declared contribution whose file is missing, and ignores a file nobody
  declared.
- A command is a template the reader inserts; it is not an execution. If the
  reader needs an action, the package needs a tool.
- When a call is denied with a capability message, quote the bsh ext grant
  command the design or the error gives, instead of weakening the manifest.
- Quote rule ids, file paths and hashes. Do not summarise a finding into a
  reassurance.
