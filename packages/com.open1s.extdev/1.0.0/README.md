# Extension DevKit

Build BSH extensions from inside BSH.

The DevKit is a process extension that turns the extension standard into
working tools: it scaffolds packages that already validate, compiles a manifest
the way the host does, reviews a package with stable rule ids, runs the declared
tools locally, builds reproducible release archives, and edits the Git market
index. Every tool returns JSON, so a finding can be cited in a review instead of
paraphrased.

    Extension DevKit 1.0.0
    id      com.open1s.extdev
    runtime process (python3, JSON-RPC 2.0 over stdio)
    surface 12 tools, 4 commands, panel, prompt, scoped context, skill,
            workflow, configuration, 4 event subscriptions

## Install

~~~text
bsh ext market install com.open1s.extdev
bsh ext grant com.open1s.extdev process.execute --scope program:python3
bsh ext grant com.open1s.extdev agent.workflows.provide
bsh ext grant com.open1s.extdev workspace.write
~~~

The manifest already asks for the capabilities the package exercises:

| Capability | Risk | Why |
|---|---|---|
| process.execute | critical | the DevKit is a Python process runtime |
| workspace.write | high | scaffold, bump, package, migrate and market write files |
| agent.workflows.provide | medium | the release workflow is a contributed tool |
| agent.tools.register, agent.prompts.provide, agent.context.provide, agent.skills.provide, ui.panels, ui.commands, events.subscribe | low/medium | the contributed surfaces |

Low-risk capabilities are granted by the community-trust default; the three
above need the explicit grants shown. Writing tools also need
`workspace.write` at call time, which is why it is in the list even though it
is not required to activate.

## The tools

| Tool | Arguments | What it does |
|---|---|---|
| `scaffold` | path, id, runtime, ... | writes a validating package skeleton |
| `validate` | path | mirrors the host's refusals as structured findings |
| `lint` | path | review rules: docs, tests, schemas, orphans, secrets, market drift |
| `check` | path, smoke | the release gate: validate + lint + hash + optional smoke |
| `smoke` | path, tool, arguments | runs the declared tools without the host |
| `explain` | topic | the standard as markdown, generated from the same tables |
| `hash` | path | the canonical package hash, file count and bytes |
| `market` | path, action, repo | entry, merge, verify, readme, list |
| `bump` | path, release | semver bump plus a dated changelog entry |
| `package` | path, out | deterministic .tar.gz with both digests |
| `migrate` | path, write | 1.x manifest to manifest 2.0 |
| `events` | limit | host events this process observed |

Every `path` argument is absolute. The process runs with its working directory
set to its own installed package, so a relative path would name the wrong tree;
the host also resolves the call scope against the workspace, which only matches
the grant when the argument is the absolute path.

## Quick start

~~~text
scaffold   /Users/me/work/hello  com.example.hello  runtime=declarative
validate   /Users/me/work/hello
lint       /Users/me/work/hello
check      /Users/me/work/hello  smoke=true
bsh ext validate /Users/me/work/hello
~~~

A scaffolded package contains the manifest, tool descriptors, a command, a
prompt, a scoped context, a panel, a skill, a configuration schema, a LICENSE, a
CHANGELOG and a test suite that runs without the host:

~~~text
cd /Users/me/work/hello
python3 -m unittest discover -s tests
~~~

## Commands, panel and skill

- `/new` asks for a path and an id, then scaffolds.
- `/audit` runs `check` and reports findings by rule id.
- `/publish` bumps, gates, packages and merges the market entry.
- `/reference` answers from `explain` instead of memory.
- The **Extension DevKit** panel runs a self-check of this extension and lists
  the findings; two more buttons open the reference topics.
- The `extdev` skill teaches the workflow: read, scaffold, validate, lint,
  smoke, gate, publish. The `release` workflow chains validate, lint and the
  market entry into one tool.

## How validation maps to the host

The validator encodes the host's refusals, not a nicer version of them:

| Family | Rule examples |
|---|---|
| envelope | `schema_version` must be 2.0, unknown top-level fields refused |
| identity | reverse-domain id grammar, semver version, semver ranges |
| runtime | kind vocabulary, declarative forbids `entry`, process/MCP need an entry, cordis spawns Node |
| limits | memory, execution, concurrency and output ceilings; manifest and contribution size caps |
| capabilities | vocabulary, duplicates, `process.execute` for a process runtime, `hooks.observe` for hooks |
| contributions | unique ids across kinds, topic grammar, hook points, event and skill ceilings |
| files | declared file exists, parses, and matches its kind's shape (tools, panels, workflows, languages, integrations, skills, providers) |
| panels | UI schema 1.0, node types, required fields, action strings, node/depth limits |
| packaging | no symbolic links, path safety |

~~text
validate -> findings[] with severity, rule, message, path, fix
lint     -> the same plus EXT### review rules
check    -> { ok, hash, files, bytes, findings, smoke? }
~~~

Errors mean the host will refuse the package. Warnings mean it will load but a
reader will struggle. Notes are opportunities, not defects.

## Security posture

- The package is a `process` runtime, so it needs `process.execute`. The host
  starts `python3 -B server.py` inside its sandbox; on macOS the sandbox
  profile denies writes outside the package, the workspace, the extension data
  root and `/tmp`.
- The DevKit makes no network requests and reads no secrets. It does read the
  packages you point it at, and `smoke` executes a package's declared entry,
  so smoke-test only packages you trust. That is stated in the tool's result
  too.
- Writing tools are gated twice: the tool descriptor declares
  `workspace.write`, and the host authorizes each call against the grant and
  the call's path scope.
- `lint` warns when a package appears to carry a credential
  (`EXT120`) before it reaches a public market.

## Development

~~~text
python3 -B -m unittest discover -s tests    # the package's own suite
bsh ext validate .                          # the host's validator
bsh ext test .                              # every declared contribution loads
bsh ext mock . validate '{"path": "..."}'
~~~

Layout:

~~~text
server.py            JSON-RPC loop, panel actions, event journal
devkit/constants.py  the standard's vocabulary (one copy)
devkit/util.py       bounded IO, digests, identifier grammars
devkit/validate.py   the host-accurate validator
devkit/lint.py       review rules EXT001..EXT120
devkit/scaffold.py   package generator
devkit/smoke.py      declarative and process dry runs
devkit/market.py     hash, index entry, merge, verify, README table
devkit/release.py    bump, deterministic archive, 1.x migration
devkit/reference.py  the embedded standard
devkit/handlers.py   tool dispatch
tests/               the suite, no host required
~~~

The DevKit validates itself in CI: `bsh ext validate`, `bsh ext test` and the
`tests/` suite all pass, and the panel's self-check lints this package.

## Compatibility

Manifest 2.0, extension API ^1.0, BSH >= 3.0.2 and < 4.0.0. Python 3.11 or newer
is required for `tomllib`.

## License

MIT.
