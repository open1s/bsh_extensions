---
name: extdev
description: Use when the reader wants to create, design, review, fix or publish a BSH extension, or asks what the Extension DevKit can do. Routes domain design, implementation and release to the matching DevKit skill.
version: 1.1.0
---

# Extension DevKit

Use this skill when a BSH extension is being designed, built, reviewed or
released. The DevKit is a command and skill surface first and a tool set
second: the tools exist so a claim can be checked, not so the model can skip
the design.

## Route first

- New extension for a specific domain, or an unclear brief: load
  extdev-design. Do not scaffold from a guessed tool list.
- A blueprint or docs/design.md exists and code is next: load extdev-build.
- The package validates and the reader wants a release: load extdev-ship.
- A question about the standard: call explain with the topic, then quote it.
- The request is ambiguous, underspecified or high-stakes: load grill-me and
  interrogate the reader one question at a time before acting.
- An existing package needs a review: run check, then design with the package
  path to compare it with its blueprint.

## The five rules

1. Read the standard, do not recall it. explain returns the same tables the
   validator enforces.
2. Every path argument is absolute. The extension process runs with its cwd
   set to its own package, so a relative path names the wrong tree.
3. Design before scaffold, scaffold before code. A domain package starts
   with a blueprint and a validating skeleton, not a hand-written manifest.
4. One build-order step per change: edit, validate, lint, smoke. Never batch
   two steps and never install with an open error.
5. Quote findings and grants, not impressions. Rule ids, file paths and the
   exact bsh ext grant command are the evidence.

## Tools at a glance

- design, blueprint, scaffold: turn a domain and a brief into a package.
- validate, lint, check, smoke, hash: check the package.
- explain: the standard and the domain catalogue.
- package, bump, market, migrate, events: release and maintenance.

Commands: /new, /plan, /domains, /audit, /publish, /reference, /grill.
The commands insert a workflow template; they do not run it for the reader.
