---
description: Scaffold a new BSH extension, with or without a domain
---

Create a new BSH extension package with the Extension DevKit.

1. If the reader named a domain or described what the extension should do,
   run the design command first. Do not scaffold a domain package from a
   guessed tool surface.
2. If the reader only wants a minimal shell, ask for an absolute directory
   and a reverse-domain id. A relative path is not enough: the scaffold tool
   needs an absolute path.
3. Call scaffold with that path, the id, and runtime declarative for a
   package that only contributes text and pure transformations, or process
   for one that runs code. For a domain package, pass domain and brief and
   let the blueprint choose the runtime unless the reader overrides it.
4. Run validate and lint on the new package and report the findings. For a
   domain package, read docs/design.md back and name the first build-order
   step.
5. Tell the reader the one command that installs it: bsh ext install <path>.
   For a process package, also name the process.execute grant.
