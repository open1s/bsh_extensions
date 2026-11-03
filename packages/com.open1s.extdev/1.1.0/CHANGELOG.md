# Changelog

## 1.1.0 - 2026-11-03

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
