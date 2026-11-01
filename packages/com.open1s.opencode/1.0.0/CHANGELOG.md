# Changelog

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
