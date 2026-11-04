---
name: extdev-build
description: Use when implementing a BSH extension from a design or docs/design.md, when a tool must be added or fixed, or when validate, lint or smoke reports a finding. Builds one slice at a time and keeps the manifest, files and capabilities in agreement.
version: 1.1.0
---

# Build a BSH extension

Use this skill when the blueprint exists and the next step is code or
contribution files.

## The loop

1. Read docs/design.md and identify the first unchecked item.
2. Implement only that item: one tool, one command, one panel or one skill.
3. Declare the contribution in extension.toml in the same change that adds
   the file.
4. Call validate. Fix errors before anything else.
5. Call lint and address warnings that matter.
6. Call smoke with the tool and a real argument. For a process package this
   proves the handshake and the wire shape.
7. Tick the checklist item and report the rule ids, file paths and the next
   step.

Never add a second surface in the same change. A manifest and a file that
disagree are the most common host failure.

## Runtime contracts

### Declarative

- No code runs. Tool bodies are echo_arguments, constant or template.
- Do not declare process, network, secret or workspace capabilities.
- A tool that needs a file, a process or HTTP is the wrong runtime; change
  the runtime rather than pretending.

### Process

- One JSON object per line on stdin and stdout. Nothing else on stdout;
  diagnostics go to stderr.
- Answer initialize with protocolVersion and the echoed token. The host kills
  the child if the token does not match.
- tools/call returns result or error; commands/execute answers panel actions
  and runtime commands.
- Read one line per request in a loop and flush after every response.
- Declare process.execute and scope it to the programs the code runs.

## Tool design

- The description says what it does and when to call it, in one or two
  sentences.
- input_schema is a JSON object with properties, required and
  additionalProperties false. Declare types; the model should not guess.
- Name the path argument path and the URL argument url, or the call scope
  cannot match the grant.
- Bound every list, diff, page and body. Return a truncated flag.
- Every failure is a sentence the caller can act on, not a traceback.

## Tests and smoke

- The package ships tests that run without the host:
  python3 -m unittest discover -s tests.
- A process package tests the handshake and one real tool call.
- smoke is the local dry run; check with smoke=true is the gate.
- Test the failure path too: bad input, missing grant, timeout, empty result.

## Security

- Read-only first. A write tool is a separate, explicitly named action.
- Never print a secret, DSN or token; report presence, not value.
- Allowlist programs, hosts, containers and check names. No free-form shell
  or arbitrary URL argument.
- Refuse an output path that equals the source path.
- Report what was skipped or truncated.

## When validate refuses

- manifest.unknown-field: remove the field or use the defined one.
- contribution.file-missing: create the file or remove the declaration.
- tool.implementation: a declarative tool needs a body.
- capabilities.process: a process runtime needs process.execute.
- panel.node-field: the node is missing a required field.

Run explain with errors for the full table, and quote the rule id in the
report.
