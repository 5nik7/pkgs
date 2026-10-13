# Working on pkgs

- The command name is pkgs. Termux's pkg is a backend frontend, not our alias.
- Human-readable, colorized reporting is the default; JSON requires --json.
- Keep package identity separate from display text. Never evaluate package data.
- Use subprocess argument arrays. Do not interpolate package names or URLs into shells.
- Completion inserts names and cannot mutate packages or perform registry searches.
- A preview may fetch metadata. Opening URLs requires the explicit picker key action.
- Termux must not receive sudo. Respect pkg's active backend and its native flags.
- Uninstall candidates come only from the selected manager's installed database.
- Preserve FZF colors and compatible user options. Respect NO_COLOR.
- Preserve user startup content, XDG/ZDOTDIR paths, and unrelated completion files.
- Test transactions with mocked managers; do not modify host packages to run tests.
- Run the focused unittest suite and shell syntax checks after changes.
- Report which device/shell combinations were actually tested; do not imply fixture
  tests provide real-device coverage.
- Update VERSION, pkgs launcher, pkgs_lib/__init__.py, completion headers, man page,
  README and changelog together for a release.
