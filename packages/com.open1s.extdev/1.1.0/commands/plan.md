---
description: Design a BSH extension for a specific domain before writing code
---

You are running the Extension DevKit domain-planning command.

Treat any text after this command as the domain brief. If there is none, ask
for it with four questions, one at a time:

1. What domain is this for, and who will use the extension?
2. Which three actions must the extension enable?
3. Which systems does it read or write, and where do their credentials live?
4. What must it never do?

Then:

1. Call the design tool with domain, brief and, when known, an absolute path
   and a reverse-domain id. Do not invent an id when the reader has a
   publisher domain.
2. Present the blueprint: the matched domain and confidence, the runtime and
   why, the contribution table, the tool surface with its scope arguments,
   the capability grants, the safety rules, the build order and the open
   questions. Say that it is a proposal, not a verified package.
3. Ask the reader to confirm or change the id, runtime and tool surface
   before writing files. If confidence is low or the domain is generic, ask
   the open questions first.
4. On confirmation, call scaffold with domain, brief, path, id and the
   confirmed runtime. It writes a validating package and docs/design.md, and
   declares only the tools whose files exist.
5. Work the build order one step at a time. After each edit call validate,
   lint and smoke; quote rule ids and file paths. Do not implement two steps
   in one change.
6. When the reader wants the blueprint saved for an existing package, call
   blueprint with the same domain, brief, id and path.

Never add a capability the blueprint does not justify. When a call is denied,
quote the bsh ext grant command from the design result instead of weakening
the manifest.
