# Extension DevKit

Design, build and ship BSH extensions from inside BSH.

The DevKit is a command and skill extension first: it turns a domain and a
one-sentence brief into a reviewable blueprint, then scaffolds a package that
already validates and walks the reader through the build order one step at a
time. The tools exist so every claim can be checked, not so the model can skip
the design.

    Extension DevKit 2.2.0
    id      com.open1s.extdev
    runtime process (python3, JSON-RPC 2.0 over stdio)
    surface 14 tools, 1 command, 5 skills, prompt, scoped context,
            workflow, configuration, 4 event subscriptions

## What changed in 2.2.0

- The reference now tracks the current host standard. `panels` documents
  collapsible `section` nodes, semantic `tone` roles, weighted table columns,
  `refresh_ms` and per-panel `theme`/`theme_dark`, input/select/checkbox action
  payloads, declared-view vs live-card semantics, and the current UI limits.
- `hooks` documents the eight points (adding `turn.start`, `turn.end` and
  `skill.load`), the `{agent, data}` envelope, the `{point, batch}` delivery
  for extism (`bsh_hook`) and wasm components (`on-event`,
  `event-type = "hook"`), the MCP gateway envelope and the network scope.
- `runtime` records the wasm component's WASI preview 2 surface: clock and
  random plus inherited stdio, with no stdin, filesystem, environment or
  socket permission.
- `validate` checks the new panel fields (widths, tone, refresh interval and
  theme ids) and accepts hook declarations on a `wasm-component` package.
- The scoped context points at the live `panels` and `hooks` topics instead of
  restating them.

## What changed in 2.1.0

- The grill-me skill and the /grill-me command: when a request is ambiguous,
  underspecified or high-stakes, interrogate the reader one hard question at
  a time — inspect first, one question per turn, a play-back of the
  decisions, a five-question cap — and only then act.

## What changed in 2.0.0

- `check` with `tool` now implies a smoke run of that tool, as its
  description always promised; `tool` alone no longer silently validates
  and reports nothing.
- `market` fails with named messages instead of raw Python exceptions when
  the package sits outside the market checkout, and `market action=list`
  resolves the checkout the same way every other action does instead of
  crashing with a TypeError when no repo can be inferred.
- `bump` refuses to downgrade the version: it fails with an explanation
  instead of rewriting extension.toml backwards.

## What changed in 1.1.0

- A domain catalogue of twelve profiles: knowledge, devops, data, web,
  documents, media, messaging, security, research, model, system and generic.
  Each profile names the runtime the domain needs, the contribution and tool
  surface, the capability scopes, the safety rules, the build order, the
  acceptance gates and the open questions.
- Two new tools: design (blueprint with an optional comparison against an
  existing package) and blueprint (write the blueprint to docs/design.md).
- Two workflow commands (/plan, /domains), three panel-action commands
  (/refresh, /selfcheck, /topics) and three new skills (extdev-design,
  extdev-build, extdev-ship); the existing extdev skill is now the router.
- The scaffold accepts domain and brief. Domain mode writes a validating
  package, docs/design.md and an implementation checklist, declares only the
  tools whose files exist, and leaves the planned tools in the checklist.
- New reference topics: design, domains, commands, skills and security, plus
  a runtime decision table.

## Install

~~~text
bsh ext market install com.open1s.extdev
bsh ext grant com.open1s.extdev process.execute --scope program:python3
bsh ext grant com.open1s.extdev agent.workflows.provide
bsh ext grant com.open1s.extdev workspace.write
~~~

The manifest asks for the capabilities the package exercises. Writing tools
also need workspace.write at call time, which is why the grant is shown even
though it is not required to activate. The design tool itself only reads a
package; blueprint writes docs/design.md.

| Capability | Risk | Why |
|---|---|---|
| process.execute | critical | the DevKit is a Python process runtime |
| workspace.write | high | scaffold, blueprint, bump, package, migrate and market write files |
| agent.workflows.provide | medium | the release workflow is a contributed tool |
| agent.tools.register, agent.prompts.provide, agent.context.provide, agent.skills.provide, ui.commands, events.subscribe | low/medium | the contributed surfaces |

## Design first

A new domain extension starts with a blueprint, not a manifest.

1. /plan with a domain and one sentence of brief.
2. design returns the matched profile, the runtime and why, the contribution
   table, full tool descriptors, the capability list with risk, scope and the
   exact bsh ext grant command, the safety rules, the build order, the gates
   and the open questions.
3. Confirm the id, runtime and tool surface.
4. scaffold with domain and brief writes a validating package and
   docs/design.md; it declares only the tools whose files exist.
5. extdev-build works one checklist item at a time: edit, validate, lint,
   smoke.
6. check with smoke=true is the gate; /publish is the release.

The blueprint is a proposal. It never installs, grants or runs anything.

## Domain profiles

| Domain | Runtime | First tools | What it is for |
|---|---|---|---|
| knowledge | declarative | checklist, cite | team playbooks, policies and checklists with no code |
| devops | process | repo_status, repo_diff, run_check | repository and CI operations without arbitrary shell |
| data | process | tables, schema, query, export | read-only database and dataset work |
| web | process | get, list, sync | one authenticated HTTP API behind a small surface |
| documents | process | extract, outline, convert | office documents without touching the source |
| media | process | probe, clip, transcode | audio, video and image work with bounded timeouts |
| messaging | process | draft, read_thread, send | chat and email with an explicit send confirmation |
| security | process | scan, findings, report | bounded scanning that reports a fingerprint, never a secret |
| research | process | search, fetch, notes | sourced web research with citations and captures |
| model | process | models, status, refresh | a model or agent provider, with a relay only when needed |
| system | process | screen_size, screenshot, click, type_text | desktop control with confirmation before input |
| generic | process | describe, inspect | an uncatalogued domain: answer the questions first |

The profile is a starting point for review, not a grant and not a
verification.

## The tools

| Tool | Arguments | What it does |
|---|---|---|
| design | domain, brief, id, runtime, path | the domain blueprint, optionally compared with a package |
| blueprint | path, domain, brief, id, runtime | write the blueprint to docs/design.md |
| scaffold | path, id, domain, brief, runtime, ... | write a validating package; domain mode writes docs/design.md |
| validate | path | mirror the host's refusals as structured findings |
| lint | path | review rules: docs, tests, schemas, orphans, secrets, market drift |
| check | path, smoke | the release gate: validate + lint + hash + optional smoke |
| smoke | path, tool, arguments | run the declared tools without the host |
| explain | topic | the standard and the domain catalogue as markdown |
| hash | path | the canonical package hash HEAD carries, its source and any uncommitted files |
| market | path, action, repo | entry, merge, verify, readme, list (hashes the commit, refuses a dirty package) |
| bump | path, release | semver bump plus a dated changelog entry |
| package | path, out | deterministic .tar.gz with both digests |
| migrate | path, write | 1.x manifest to manifest 2.0 |
| events | limit | host events this process observed |

Every path argument is absolute. The process runs with its working directory
set to its own installed package, so a relative path would name the wrong
tree; the host also resolves the call scope against the workspace, which only
matches the grant when the argument is the absolute path.

### The market hash is the commit, not the files on disk

The host installs a market entry by cloning the provider and hashing that
checkout, and a clone carries committed files only. `market` therefore hashes
`HEAD` and refuses a package with uncommitted changes: hashing the working
tree would fold in ignored files (a `__pycache__` from a test run is the
usual one) and declare a digest no clone can reproduce, which the host refuses
with a `package.integrity` denial. Commit the package, then run
`market action=merge`; `verify` reads the same commit and names a dirty tree
instead of passing it.

## Commands and skills

| Command | What it does |
|---|---|
| /plan | interview, blueprint, confirm, scaffold, build one step at a time |
| /new | scaffold a minimal shell or a domain package |
| /audit | check, then compare the package with its blueprint |
| /publish | bump, gate, package, merge the market entry |
| /reference | answer from explain instead of memory |
| /grill | interrogate an ambiguous request before acting on it (the grill-me skill) |

The five skills:

- extdev is the router: which skill for design, build or ship, and the five
  rules that apply everywhere.
- extdev-design turns a domain brief into a blueprint and a confirmed
  scaffold, with the selection heuristics and the anti-patterns.
- extdev-build implements one checklist item at a time, with the declarative
  and process contracts, tool schema design, tests and security.
- extdev-ship covers check, bump, package, market, signing and the release
  record.
- grill-me interrogates an ambiguous or high-stakes request: one
  self-contained question at a time, a play-back of the decisions, then the
  work.

Commands insert a workflow template into the input; they do not execute it.
The model decides what to do next.

## Quick start

~~~text
design    /Users/me/work/warehouse  domain=data  brief="Query the warehouse read-only and export CSV"
blueprint /Users/me/work/warehouse  domain=data
scaffold  /Users/me/work/warehouse  com.example.warehouse  domain=data
validate  /Users/me/work/warehouse
lint      /Users/me/work/warehouse
check     /Users/me/work/warehouse  smoke=true
bsh ext install /Users/me/work/warehouse
~~~

A domain scaffold contains the manifest, docs/design.md with the blueprint
and checklist, the domain commands, prompt, scoped context, skill,
the working describe/echo tools, a configuration schema, a LICENSE, a
CHANGELOG and a dependency-free test suite:

~~~text
cd /Users/me/work/warehouse
python3 -m unittest discover -s tests
~~~

## How validation maps to the host

The validator encodes the host's refusals, not a nicer version of them:

| Family | Rule examples |
|---|---|
| envelope | schema_version must be 2.0, unknown top-level fields refused |
| identity | reverse-domain id grammar, semver version, semver ranges |
| runtime | kind vocabulary, declarative forbids entry, process/MCP need an entry |
| limits | memory, execution, concurrency and output ceilings; file size caps |
| capabilities | vocabulary, duplicates, process.execute for a process runtime, hooks.observe for hooks |
| contributions | unique ids across kinds, topic grammar, hook points, event and skill ceilings |
| files | declared file exists, parses, and matches its kind's shape |
| packaging | no symbolic links, path safety |

~~~text
validate -> findings[] with severity, rule, message, path, fix
lint     -> the same plus EXT### review rules
check    -> { ok, hash, files, bytes, findings, smoke? }
design   -> { domain, extension, contributions, tools, capabilities, ... }
~~~

Errors mean the host will refuse the package. Warnings mean it will load but a
reader will struggle. Notes are opportunities, not defects.

## Security posture

- The package is a process runtime, so it needs process.execute. The host
  starts python3 -B server.py inside its sandbox; on macOS the sandbox profile
  denies writes outside the package, the workspace, the extension data root
  and /tmp.
- The DevKit makes no network requests and reads no secrets. It does read the
  packages you point it at, and smoke executes a package's declared entry, so
  smoke-test only packages you trust. That is stated in the tool's result too.
- Writing tools are gated twice: the tool descriptor declares workspace.write,
  and the host authorizes each call against the grant and the call's path
  scope.
- lint warns when a package appears to carry a credential (EXT120) before it
  reaches a public market.
- design and blueprint quote the exact grants a blueprint needs; they never
  grant, install or run anything.

## Development

~~~text
python3 -B -m unittest discover -s tests    # the package's own suite
bsh ext validate .                          # the host's validator
bsh ext test .                              # every declared contribution loads
bsh ext mock . design '{"domain": "data"}'  # one tool against a mock host
~~~

Layout:

~~~text
server.py            JSON-RPC loop, event journal
devkit/domains.py    the twelve domain profiles and the matcher
devkit/design.py     blueprint, comparison, docs/design.md writer
devkit/constants.py  the standard's vocabulary (one copy)
devkit/util.py       bounded IO, digests, identifier grammars
devkit/validate.py   the host-accurate validator
devkit/lint.py       review rules EXT001..EXT120
devkit/scaffold.py   package generator, domain-aware
devkit/smoke.py      declarative and process dry runs
devkit/market.py     hash, index entry, merge, verify, README table
devkit/release.py    bump, deterministic archive, 1.x migration
devkit/reference.py  the embedded standard and the catalogue topic
devkit/handlers.py   tool dispatch
tests/               the suite, no host required
~~~

The DevKit validates itself in CI: bsh ext validate, bsh ext test and the
tests/ suite all pass.

## Compatibility

Manifest 2.0, extension API ^1.0, BSH >= 3.0.2 and < 4.0.0. Python 3.11 or
newer is required for tomllib.

## License

MIT.
