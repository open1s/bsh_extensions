---
description: Scaffold a new BSH extension
---

Create a new BSH extension package with the extension devkit.

1. Ask which directory and which reverse-domain id to use if the reader has not
   said. A relative path is not enough: the scaffold tool needs an absolute path.
2. Call `scaffold` with that path, the id, and `runtime` set to
   `declarative` for a package that only reads files, or `process` for one
   that runs code.
3. Run `validate` and `lint` on the new package and report the findings.
4. Tell the reader the one command that installs it: `bsh ext install <path>`.
