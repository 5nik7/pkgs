# Validation and device acceptance

Run the focused suite and syntax checks without installing host packages:

```sh
python3 -m unittest discover -s tests -v
bash -n pkgs install.sh uninstall.sh completions/pkgs.bash
zsh -n completions/pkgs.zsh
fish -n completions/pkgs.fish
```

Tests use temporary homes, caches, state, and installation prefixes. Transactions
are mocked. The real-fzf PTY tests use fake package metadata and skip when fzf is
unavailable. They check actual option parsing, multiselection, metadata previews,
compatible defaults/options files, and cancellation of a slow metadata child.
Read-only query tests exercise timeouts; migration tests verify backups,
permissions, symlinks, exact surrounding bytes, conflicts, and repeat installs.
See `VALIDATION.json` for the environment and measured evidence for this release.

## Establish command and shell identity

In the real Zsh session run `whence -a pkgs fzf`, `print -rl -- $fpath`, and
`./pkgs doctor`. Use `./pkgs` or the installed absolute launcher while another
`pkgs` precedes it on PATH. Do not install a replacement fzf or change PATH to
perform diagnostics. Check both the reported fzf version and PATH/fallback source.

The agent's exported environment may differ from the interactive shell. Compare
these in that shell, retaining its normal configuration:

```zsh
./pkgs install --query fzf --dry-run --debug
(env -u FZF_DEFAULT_OPTS -u FZF_DEFAULT_OPTS_FILE ./pkgs install --query fzf --dry-run --debug)
```

If only the first fails, inspect both defaults and the options file for
unsupported options or output-changing settings. `--filter`, `--accept-nth`,
and custom accept/reload bindings are not compatible picker defaults. Normal
colors and compatible bindings must remain effective.

## File-only completion and migration

1. Record startup-file checksums and symlink targets before testing. Fresh
   Bash/Zsh setup must leave them unchanged and must not create absent files.
2. From Zsh run `FPATH="$FPATH" ./pkgs completion zsh install`, or explicitly
   select a directory already in `$fpath` with `--directory DIR`. Repeat it;
   no extra backups or content changes should occur. Check `status --json`.
3. Try a custom directory containing spaces. Without reliable context or an
   explicit override, Zsh setup must fail with instructions, not install into
   an assumed inactive XDG directory.
4. In Bash check bash-completion is installed **and loaded**. Test its user
   autoload directory, `BASH_COMPLETION_USER_DIR`, and the missing-loader case.
   An explicit file-only installation must describe unverified activation.
5. Follow the printed one-time reload instructions. Test command and package
   completion in Bash and Zsh; with fzf-tab present there must be no nested picker.
   Completions insert names and never transact.
6. Test exact 0.1.0 block migration only in a disposable copy of startup files
   first. Verify backups, symlinks, permissions, surrounding whitespace, and old
   completion cleanup. Edited/malformed/duplicate blocks must stop migration.
7. Change XDG_DATA_HOME/ZDOTDIR after setup while retaining XDG_STATE_HOME;
   update and uninstall must use recorded managed paths. Do not remove unrelated
   files in old directories. Inspect retained notices and backups.
8. In Fish check unchanged `conf.d` installation, next-prompt activation, pkgs
   multiselection, and preservation of another command's Tab binding.

The main installer uses the same rules and supports repeatable
`--completion-dir SHELL=DIR`. Its dry run preflights destinations without writes.

## Picker and cancellation

Use an isolated cache to compare cold and warm operation, without deleting the
normal cache. Run `./pkgs`, `-h`, `-H`, `--help`, `--version`, and `doctor`, then:

```sh
./pkgs install --dry-run --debug
./pkgs install --query fzf --dry-run --debug
./pkgs search --debug
./pkgs search fzf --debug
./pkgs uninstall --dry-run --debug
```

- Bare/help commands must not inspect catalogs or start fzf. Picker preparation
  must contain no catalog-wide ownership queries. Record catalog and launch
  timings separately; target under one second of overhead after inventory is ready.
- Verify fresh `[i]` markers. Uninstall must only offer selected-manager/scope
  packages; external commands never become removal targets.
- Highlight source-installed fzf. Its preview should show path/fallback evidence
  and `[e]` after checking ownership. Later opens may use valid cached evidence;
  changing the executable or package database must invalidate it.
- Check Tab/Shift-Tab multiselection and clean dry-run identifiers. Ctrl-X toggles
  a colorized, wrapped preview. Alt-I hides/shows installed rows. Explicit Alt-O
  uses the platform URL handler; missing URLs show a notice.
- Esc and Ctrl-C must cancel promptly, including while a preview is slow. Inspect
  subprocesses and temporary directories for leftovers. A failed manager query
  must be reported as failure, not empty results or successful cancellation.
- Check NO_COLOR and `--color never`, along with ordinary fzf theme preferences.
  Test slow/failing managers with fixtures; never alter host packages to simulate
  failure. Interactive transactions must retain their native prompts/time limits.

Native Termux APT read-only evidence, mocked Linux backends, real-fzf PTYs,
interactive shell acceptance, and other-device results are separate categories.
Do not report one as coverage of another. Real transactions are outside this
fix-validation procedure.
