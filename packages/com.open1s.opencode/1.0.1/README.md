# OpenCode Zen for BSH

Free [OpenCode Zen](https://opencode.ai/zen) models inside BSH, through the
anonymous lane OpenCode's own CLI uses. No account, no API key, no subscription.

The package contributes the **OpenCode Zen** model provider (keyless), four
tools — `opencode__relay_start`, `opencode__relay_stop`, `opencode__status` and
`opencode__models` — and a context that tells the agent when to start the relay.
The provider points at a loopback relay this package runs, because a provider
descriptor cannot express the wire shape the free lane requires.

## Why a relay instead of a plain provider

A BSH provider descriptor is a static document: base URL, protocol, model list,
per-model metadata and a keyless flag. It cannot add HTTP headers, mint a
session id, or rename a tool. The Zen free tier refuses a request without all
three:

| Requirement | Plain descriptor | This package |
|---|---|---|
| Canonical `ses_*` session id in `x-opencode-session` | no | relay mints one per conversation |
| CLI header set (`x-opencode-client`, `x-opencode-project: global`, `X-Session-Id`, …) | no | relay sends it |
| `bash` **and** `read` in the tools array, non-empty schemas | no — BSH has `read_file` | relay renames `read_file` to `read` and maps the call back |
| Streaming body | yes | relay forces it and aggregates for non-stream callers |
| Free model catalog | baked only | `opencode__models` reads the live catalog |

That is the same split the reference package
([opencode2dsh](https://github.com/FishBottle7/opencode2dsh)) makes in its
`sidecar` mode. BSH's descriptor contract has no code-level adapter API, so the
relay is the framework-honest shape.

## What this needs from BSH

Three framework facts line up so an installed BSH package is usable with no extra
step, and all three are part of the BOS change that ships with this release:

1. **Providers are read after the extension host opens.** The launch refresh
   used to run before any theme/status/panel query opened the host, so
   `providers/models/<id>.json` was read from an empty host and never surfaced.
2. **A descriptor can declare an anonymous lane.** `requires_key = false` on
   the provider document makes the build send no credential instead of
   demanding a vault entry for an endpoint that never wanted one.
3. **`startup = "on-startup"` warms the package at launch.** The host spawns the
   extension process after load, so `server.py` binds the relay before the
   first model call. Without this the process would wait for the first tool
   call and the first chat after launch would hit a closed port.

Build BSH from a checkout that includes those three fixes. On an older build the
tools still install but the provider does not appear; upgrading BSH is the fix,
not a package-side workaround.

## Requirements

- BSH 3.x with extension API 1.0 and the three launch fixes above
- Python 3.8 or newer on `PATH` as `python3`
- Outbound HTTPS to `opencode.ai`

## Install

`process.execute` is a critical capability and `network.http` is high risk for a
community package, so grant them before installing:

~~~text
bsh ext grant com.open1s.opencode process.execute --scope program:python3 --note "OpenCode Zen relay"
bsh ext grant com.open1s.opencode network.http --scope any --note "live Zen catalog"
bsh ext market install com.open1s.opencode
~~~

From a checkout, `bsh ext install packages/com.open1s.opencode/1.0.1` installs
the same package. Restart BSH after installing so the launch refresh reads the
new inventory and warms the package.

## Use

1. Restart BSH once after installing. The host warms the package, and the relay
   binds `127.0.0.1:18765` before the first model call.
2. Pick **OpenCode Zen** in the model picker, then a free model such as
   `deepseek-v4.1-flash-free`.
3. Chat.

If `opencode__status` says the relay is not running, call
`opencode__relay_start` (or type `/` in the composer and pick the extension's
**start** command). The tool is idempotent and returns the base URL.

No API key is needed: the descriptor declares `requires_key = false`, and the
relay replaces whatever credential BSH sends with the lane's literal
`Bearer public`.

Call `opencode__relay_stop` to stop the relay, and `opencode__status` to see
whether it listens, how many requests it forwarded and the last upstream error.

### Relay lifetime

The relay runs inside the extension's process runtime. BSH starts that process at
launch because the manifest declares `startup = "on-startup"`, and keeps it while
the extension host configuration is unchanged. A workspace switch or a preset
change that reopens the host respawns the process and the relay comes back with
it; a BSH restart does the same. If the process failed to start (a missing
`process.execute` grant, a taken port), `opencode__status` reports why and
`opencode__relay_start` retries.

### Port

The provider points at `http://127.0.0.1:18765/v1`. If that port is taken, stop
whatever owns it; `opencode__relay_start` can bind another port for diagnostics,
but the provider descriptor would then need the same edit.

## Free models

The descriptor is baked from the live catalog on 2026-11-01. The eight free
models it lists are the ones whose input and output prices are both zero:
`big-pickle`, `beam-free`, `flint-40b-free`, `mimo-v2.6-flash-free`,
`nemotron-3.5-super-vl-free`, `nemotron-3.5-lightning-free`,
`deepseek-v4.1-flash-free` and `glm-5.3-flash-free`.

Because a desk-checked list rots, `opencode__models` reads
`https://opencode.ai/inference/v1/models` every time and reports the live free
roster with input types, output caps, context windows and reasoning support. On
a transport failure it falls back to the baked descriptor, and the result's
`source` and `error` fields say which answer you got. Maintainers regenerate the
descriptor with:

~~~text
python3 scripts/refresh_provider.py
python3 scripts/refresh_provider.py --check   # CI: exit 1 when stale
~~~

Image input follows each model's declared modalities: MiMo, Nemotron Super VL,
DeepSeek V4.1 Flash and GLM 5.3 declare image input, the others are text only.

## Known limits

- **Per-IP quota.** The anonymous lane is quota-limited per egress. HTTP 429
  `FreeUsageLimitError` means this network has spent it; wait or change egress.
  The relay passes the upstream status and body through, so BSH shows it.
- **Client-shape refusal.** HTTP 403 `FreeTierError` means upstream refused the
  request shape even with the disguise. The reference package documents this as
  a moving target; rerun `opencode__status` and `opencode__models` to see
  whether the lane answers at all from this network.
- **Region blocks.** Some models answer 403 `REGION_BLOCKED` from some
  countries. The relay preserves the upstream body.
- **Thinking levels.** BSH's reasoning-effort menu is a shell preference, not a
  per-model ladder; the descriptor cannot advertise the levels each Zen model
  accepts. Reasoning models think with their provider default unless the reader
  picks an effort.
- **Context windows.** BSH's model descriptor has no context field, so the
  provider file cannot carry them. The context meter estimates; the live values
  are in `opencode__models` and in `zen_catalog.STATIC_CONTEXT`.
- **One model list per install.** A newly free model appears in
  `opencode__models` immediately but in the picker only after
  `scripts/refresh_provider.py` republishes the descriptor and the package is
  upgraded; the relay itself accepts any model id the lane serves.
- **No live verification from every egress.** The shaping logic is covered by
  offline tests against a mock upstream. On 2026-11-01 the development egress
  answered 429 for every free model, so the end-to-end call could not be
  observed here; the first reader on a network with quota is the live test.

## Security

- The relay binds `127.0.0.1` only and keeps no credential. Any local process
  can use it while it runs; `opencode__relay_stop` closes it.
- Nothing is stored: no token, no session file. Session ids live in memory for
  the process's lifetime (bounded to 1024 conversations).
- The child process gets BSH's cleared environment, a package-root working
  directory and `PYTHONDONTWRITEBYTECODE=1`, so the immutable package hash is
  never dirtied by `__pycache__`.
- Every request leaves the machine only for `opencode.ai`.

## Development

~~~text
python3 -m unittest discover -s tests -v
bsh ext validate .
bsh ext test .
~~~

`bsh ext mock` starts a sandboxed child with `sandbox-exec`; inside another
macOS sandbox (as in a sandboxed agent shell) that call is denied before the
extension runs. Outside it the mock works normally. The unit tests drive the
same JSON-RPC handshake and the relay directly, so they do not depend on it.

## Mirror of opencode2dsh

| opencode2dsh | here |
|---|---|
| Native DSH `LlmAdapter` streaming from Zen | Loopback OpenAI-compatible relay + BSH provider descriptor |
| Anonymous free lane, `Bearer public` | Same, declared `requires_key = false` |
| CLI-identical headers, session/project ids | Same header set, canonical `ses_*` ids, conversation-stable |
| Live catalog: live ∩ free-by-metadata, cache/static fallback | Live catalog ∩ zero-price, in-memory cache, baked descriptor fallback |
| Selectable thinking levels | Provider default effort; BSH's effort menu is global |
| Image input by models.dev modalities | `input_types` from the live catalog's modalities |
| Health snapshot file | `opencode__status` tool result |
| Classified error surfaces | Upstream status and body pass through unchanged |
| IP pool / proxy rotation | Not implemented; egress is the host's network |
| Local OpenCode delegation | Not implemented |

## License

MIT. The wire-shape measurements are ported from
[opencode2dsh](https://github.com/FishBottle7/opencode2dsh) (MIT).
