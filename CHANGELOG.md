# Changelog

## 0.1.1

- Make Bash/Zsh completion installation file-only, with explicit directory
  overrides, caller-supplied FPATH, loader-aware Bash discovery, and separate
  content/activation reporting. Keep Fish setup and bindings unchanged.
- Record managed completion destinations and hashes; migrate exact legacy
  startup blocks with backups while preserving symlinks and unrelated bytes.
  Refuse edited blocks/files and keep repeat installs idempotent.
- Open pickers without catalog-wide ownership queries. Fetch external evidence
  lazily in bounded previews; retain source-built fzf support and cached markers.
- Replace rejected fzf `--expect=` with `--no-expect` in both picker paths.
  Run helpers without shell startup hooks and preserve compatible fzf settings.
- Add read-only query budgets, progress/timing diagnostics, accurate ownership
  failure handling, command-shadowing diagnostics, and cancellation cleanup.
- Expand mocked-manager, installation/migration, and real-fzf PTY regressions;
  record native Termux APT read-only checks separately from device acceptance.

## 0.1.0

- Modular Bash launcher and Python standard-library core.
- Usage on bare invocation; -h/-H/--help, version, human-readable default output.
- Termux APT/pacman detection and supported Linux system backends.
- npm, pip, uv-tool and RubyGems with explicit scopes and catalog limits.
- Multi-select install/remove/search picker with colorized, wrapped previews.
- Alt-I installed toggle, Ctrl-X preview toggle, Alt-O platform-aware URL opening.
- Package ownership evidence for external executables.
- Offline completion candidates and Bash/Zsh/Fish integrations.
- Idempotent completion setup, config, user installer/uninstaller and man page.
- Mock-backed regression tests and isolated installer verification.
