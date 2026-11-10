# Changelog

## 1.0.0 — 2026-11-05

- Initial release: nine real macOS computer-use tools (`screen_size`,
  `screenshot`, `cursor_position`, `mouse_move`, `mouse_click`, `mouse_drag`,
  `scroll`, `type_text`, `key_press`), a right panel with a Screenshot action
  and a `refresh` command, the `computer-safety` skill, the `inspect` workflow
  and the `desktop.control` / `desktop.refresh` integrations.
- CoreGraphics is driven through ctypes; the package needs no third-party
  Python packages.
- Ships the MIT LICENSE, protocol tests under `tests/` and this changelog
  after the DevKit review.
