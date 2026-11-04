---
description: BSH extension packages in this workspace
paths: extension.toml, **/extension.toml, packages/**/extension.toml, docs/design.md, **/docs/design.md
---

This workspace contains BSH extension packages (manifest 2.0). The Extension
DevKit tools validate, lint, check, smoke, hash, market, bump, package and
migrate one absolute package path at a time; design and blueprint turn a
domain brief into a plan; scaffold writes a validating package.

A package must ship every file its manifest declares. The host installs from a
content-addressed store, so the canonical package hash changes with any byte;
the market index records that hash.

A domain package records its plan in docs/design.md: the matched domain, the
runtime and why, the contribution and tool surface, the capability grants,
the safety rules, the build order and the acceptance gates. Read it before
editing a domain package, and update the checklist as each item lands.

The DevKit itself contributes commands (/new, /plan, /domains, /audit,
/publish, /reference, /grill) and five skills (extdev, extdev-design,
extdev-build, extdev-ship, grill-me). Commands insert a workflow template;
the tools do the checks.
