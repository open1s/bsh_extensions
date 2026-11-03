---
description: BSH extension packages in this workspace
paths: extension.toml, **/extension.toml, packages/**/extension.toml
---

This workspace contains BSH extension packages (manifest 2.0). The Extension
DevKit tools `validate`, `lint`, `check`, `smoke`, `hash`,
`market`, `bump`, `package` and `migrate` operate on one absolute
package path at a time.

A package must ship every file its manifest declares. The host installs from a
content-addressed store, so the canonical package hash changes with any byte;
the market index records that hash.
