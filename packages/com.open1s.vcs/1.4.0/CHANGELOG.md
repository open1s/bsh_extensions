# Changelog

## 1.4.0 - 2026-11-16

- First market release under `com.open1s.vcs` (previously the in-tree
  `com.bos.bsh.change-history` example).
- Cordis package: one `change_history` tool (status, log, diff, show, new,
  describe, edit, squash, rebase, restore, undo) over jj or git, and a live
  Git panel.
- Every effect runs through the host's capability-gated terminal seam;
  arguments are shell-quoted, `.gitignore` is respected, and calls are
  serialized for jj's working-copy lock.
- Market packaging: `packages/com.open1s.vcs/1.4.0/` layout,
  repository/homepage metadata, LICENSE, `tests/` layout and a host range
  aligned with the 3.x/4.x marketplace (`>=3.0.2, <5.0.0`).
