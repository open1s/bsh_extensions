# Changelog

## 1.0.3 — 2026-11-03

- **Consolidated to 3 usage entries** (down from 6): the 4 individual tools are
  now a single `relay` tool with action subcommands (start, stop, status, models).
  The `start` command remains for manual restarts.
- The baked provider descriptor is regenerated from the live catalog: it now
  lists ten free models, adding `pulse-alpha-free` (text+image, 131072 output)
  and `crouton-alpha-free` (text+image, 270000 output), both 1048576 context.
- `STATIC_CONTEXT` in zen_catalog.py gains the two new context windows, so the
  static fallback reports honest windows for them too.
- No relay or protocol change; the wire shape was re-verified against the live
  anonymous lane (upstream accepted the gated request and answered the
  documented 429 FreeUsageLimitError on a spent per-IP quota).

## 1.0.2 — 2026-11-01

- The relay's request log is guarded: if the host that spawned the process has
  already closed the stderr pipe, a request is still answered instead of
  failing before the response (the empty-reply case seen when a stale relay
  process outlived its host).
- No protocol or model-list change; 1.0.1 remains installable.

## 1.0.1 — 2026-11-01

- The relay now binds at launch: the manifest declares startup = "on-startup"
  and the process autostarts the relay on the declared port, so the provider is
  usable before the first tool call. `relay` with action=start stays idempotent
  and retries when the launch bind failed.
- Adds the `start` command to the composer palette for a manual restart.
- Requires the BOS change that warms on-startup runtimes at host load, in
  addition to the provider refresh and `requires_key` fixes from 1.0.0.

## 1.0.0 — 2026-11-01

- Initial release: the **OpenCode Zen** model provider, a loopback relay that
  speaks the anonymous lane's wire shape, and the `relay_start`, `relay_stop`,
  `status` and `models` tools.
- The relay mints canonical `ses_*` ids per conversation, sends the CLI header
  set, forces streaming, renames `read_file` to the gate's `read` and maps the
  tool call back, and injects the `bash`/`read` pair when the host sends none.
- The provider descriptor declares `requires_key = false`: the build sends no
  credential for the anonymous lane instead of demanding a vault entry.
- `opencode__models` reads the live catalog and decides "free" from the prices;
  the baked descriptor is the offline fallback.
- Requires the BOS change that opens the extension host before the launch
  provider refresh and honours `requires_key` in provider descriptors.
- `-B` and `PYTHONDONTWRITEBYTECODE=1` keep the installed package hash free of
  `__pycache__`.
