# Changelog

## 2.0.0 - 2026-11-04

- `check` with `tool` now implies a smoke run of that tool, as its
  description always promised; `tool` alone no longer silently validates
  and reports nothing.
- `market` fails with named messages instead of raw Python exceptions when
  the package sits outside the market checkout, and `market action=list`
  resolves the checkout the same way every other action does instead of
  crashing with a TypeError when no repo can be inferred.
- `bump` refuses to downgrade the version: it fails with an explanation
  instead of rewriting extension.toml backwards.
- `lint` no longer flags a coverage archive as EXT062; only the known
  build directories count as build output.
- `package` refuses an `out` directory inside the package, and reports
  any hashed build output it did include, so a release never depends on
  who ran the tests.

## 1.1.0 - 2026-11-03

- Fix migrate for 1.x manifests: a declarative runtime no longer keeps the
  forbidden `entry` key under runtime.config, scalar contributes values are
  accepted, tables with an `id` carry their inline payload into
  [contribution.payload] instead of nesting it into the id, and non-string
  entries fail with a named message instead of crashing.
- Add a domain-first design surface: a twelve-profile catalogue (knowledge,
  devops, data, web, documents, media, messaging, security, research, model,
  system, generic), the design tool and the blueprint tool.
- Add the design and domains commands and the extdev-design, extdev-build and
  extdev-ship skills; extdev is now the router.
- Teach scaffold the domain and brief arguments: domain mode writes a
  validating package, docs/design.md and an implementation checklist, and
  declares only the tools whose files exist.
- Add the design, domains, commands, skills and security reference topics and
  a runtime decision table.
- Declare the panel actions refresh, selfcheck and topics as command
  contributions, so every panel button resolves through the host command
  seam instead of failing with "was not found".
- Add default_domain to configuration.
- Make the canonical package hash use the host walk order (WalkDir
  pre-order with per-directory name sorting), so the DevKit hash equals
  bsh ext hash again.
- Keep the 1.0.0 tools, commands and behaviour; the new surface is additive.

## 1.0.0 - 2026-11-03

- First release: scaffold, validate, lint, check, smoke, explain, hash, market,
  bump, package and migrate, with commands, a self-checking panel, a scoped
  context, a skill, a release workflow, configuration and four event
  subscriptions.
