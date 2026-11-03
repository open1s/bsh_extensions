---
name: extdev
description: Build, review and publish a BSH extension with the Extension DevKit
version: 1.0.0
---

# Building a BSH extension

Use this skill when the reader wants to create, fix, review or publish a BSH
extension.

1. Read the standard first: call `explain` with `overview`, then the topic
   that matches the question (`manifest`, `runtime`, `capabilities`,
   `contributions`, `tools`, `panels`, `protocol` or `market`).
2. If there is no package yet, call `scaffold` with an absolute path, a
   reverse-domain id and `runtime` = `declarative` (no code) or `process`
   (a JSON-RPC server).
3. After every edit, call `validate` and fix errors before anything else.
   Then call `lint` and address warnings that matter.
4. Call `smoke` to run the declared tools once. A process package must echo
   the handshake token; a declarative tool must return what its body says.
5. Before publishing: `bump`, `check` with `smoke` true, `package`,
   then `market` with `action` = `merge` and `action` = `verify`.
6. Report rule ids and file paths, not impressions. If a capability is
   missing, quote the grant command instead of editing the manifest.
