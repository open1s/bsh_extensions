---
name: extdev-design
description: Use when the reader wants a new BSH extension for a specific domain, when the domain is named but the tool surface is not, or when a package needs a blueprint before code. Turns a domain brief into a reviewable extension design.
version: 1.1.0
---

# Design a domain extension

Use this skill before any manifest is written for a new domain. The output is
a blueprint: runtime, contribution plan, tool descriptors, capability grants,
safety rules, build order, gates and open questions.

## 1. Interview, one question at a time

Ask only what the brief does not answer:

1. What is the domain, and who uses the extension?
2. Which three actions must it enable first?
3. Which systems does it read or write, and where do their credentials live?
4. What must it never do?
5. Is there an existing package, an id, or a publisher domain?

Do not ask for a technology when the reader named the work. A Jira request is
web work; a SQL helper is data work; a team playbook is knowledge work.

## 2. Choose the domain

Call explain with topic domains, or call design directly. The catalogue is:
knowledge, devops, data, web, documents, media, messaging, security,
research, model, system and generic.

- Name the work, not the tool: a browser capture tool is research, not web.
- If two profiles fit, choose the one whose tools can be implemented this
  week and say what is deferred.
- If confidence is low or the profile is generic, stop and ask the open
  questions. A generic blueprint with one honest tool beats a guessed surface
  with six.

## 3. Call design

Pass domain, brief, and when known an absolute path and a reverse-domain id.
Do not invent a publisher domain; com.example is a placeholder and must be
replaced before release.

Read the result, not only the markdown:

- domain.key, confidence and signals: why this profile matched.
- extension.runtime and runtime_reason: declarative for text and pure
  transformations, process when code, files, network or native APIs are
  needed.
- contributions: every kind, id and file. Tool ids and command ids must be
  unique across kinds.
- tools: input_schema, scope_arguments, capabilities and returns. Every path
  argument is named path; every URL argument is named url.
- capabilities: risk, why, scopes and grants. High and critical capabilities
  are explicit grants, not automatic ones.
- warnings: a requested runtime that contradicts the profile.
- existing: when a path was given, missing contributions, capabilities, tool
  files and unjustified high-risk capabilities.

## 4. Present and confirm

Present, in this order: domain and confidence, runtime and why, contribution
table, tool surface, capability grants, safety rules, build order, open
questions. Say that the blueprint is a proposal.

Ask the reader to confirm or change the id, runtime and tool surface. Nothing
is written before that confirmation.

## 5. Scaffold

Call scaffold with domain, brief, path, id and the confirmed runtime. It
writes a validating package plus docs/design.md. It declares only the tools
whose files exist; the planned tools stay in the checklist.

For an existing package, call blueprint instead of scaffold to write
docs/design.md without touching the package.

## Selection heuristics

- The smallest surface that does the work wins: one tool and one command beat
  four tools and a panel nobody asked for.
- A command is a template, not an execution. If the reader needs an action,
  the design needs a tool.
- A skill teaches a workflow. Do not use a skill to hide a missing tool.
- A prompt holds stable rules; a context holds facts that only apply under
  some paths.
- Add a panel only when it shows live state the reader checks repeatedly.

## Do not

- Do not copy a profile's capability list into a manifest without matching it
  to a code path.
- Do not ask for network, process, secret or Computer Use access because a
  future version might need it.
- Do not declare a tool before its file exists.
- Do not publish a design whose id still says com.example.
