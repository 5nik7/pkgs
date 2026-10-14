# pkgs 0.1.1

A fuzzy package browser and package-manager frontend for **Termux and Linux**.
Bash launcher, Python standard-library core, no pip dependencies.
The command is **`pkgs`**. It does not replace Termux's `pkg`.

## Install

Requirements: Bash 4+, Python 3.9+, and fzf 0.48+ for interactive pickers.
Native completions target Bash 4+, Zsh 5.8+, and Fish 3.6+.
Your selected package manager must already be installed.

Existing source installations such as `~/.fzf/bin/fzf` are supported. pkgs uses
the first fzf on PATH, falling back to that source-build location. `pkgs doctor`
reports the resolved executable, version, and any other `pkgs` shadowing it.
The installer does not fetch dependencies or change package installations.

After extracting the release, enter its directory. From your actual Zsh session,
provide its completion search path for this invocation only:

```zsh
cd pkgs-0.1.1
FPATH="$FPATH" ./install.sh --dry-run
FPATH="$FPATH" ./install.sh
```

The default application prefix is `~/.local`. The installer installs the command,
man page, and completions for shells found on PATH. **Bash and Zsh completion
installation is file-only:** it never adds startup blocks, source statements,
compinit/compdef calls, or fpath changes. It preflights all destinations before
installing. An uncertain destination is an error, with override instructions.

```sh
# Explicit destinations (choose directories your shell already uses):
./install.sh --completion-dir "zsh=$PREFIX/share/zsh/site-functions"
# Skip completion setup, or use a custom application prefix:
./install.sh --prefix "$HOME/.local" --no-completions
./pkgs doctor
```

The `$PREFIX` example is appropriate only when that directory is in your Zsh
`fpath`. pkgs cannot inspect a parent shell's live arrays. It does not launch
interactive shells or source startup files to guess them. It reports the
resolved path and activation evidence separately from completion file status.

Use the printed one-time reload instructions in your current shell. In Zsh,
first verify the destination is in `$fpath`, then use your normal completion
reload, or run `autoload -Uz compinit; compinit; autoload -Uz _pkgs; compdef _pkgs pkgs`.
In Bash, with bash-completion loaded, a new session autoloads the file; `source`
the printed completion file to register it in the current session. No reload
command is written into startup files.

Fish keeps its existing completion file and managed `conf.d` setup. Run
`source ~/.config/fish/conf.d/pkgs.fish` (adjust for XDG_CONFIG_HOME), then return
to the prompt. Rebinding Fish keys later requires `__pkgs_bind_tab` again.

You can run `./pkgs` directly from the checkout. Check `whence -a pkgs fzf` in
Zsh if an older command on PATH still runs. The installer warns about shadowing
but does not change PATH. Use `man pkgs` if MANPATH includes the install prefix.

## Commands

| Command | Result |
|---|---|
| `pkgs` | Usage, without starting fzf |
| `pkgs help`, `pkgs -h`, `pkgs -H`, `pkgs --help` | Usage |
| `pkgs --version` | Version |
| `pkgs install` | Multi-select installation picker |
| `pkgs install --query editor` | Search and pick |
| `pkgs install git ripgrep` | Install exactly those names |
| `pkgs uninstall` | Picker containing installed packages only |
| `pkgs uninstall git` | Remove an installed package |
| `pkgs remove git` | Alias for uninstall |
| `pkgs search editor` | Read-only picker; Enter shows details |
| `pkgs list` | Readable available/installed inventory |
| `pkgs list --installed` | Installed packages |
| `pkgs list --json` | Structured inventory |
| `pkgs info git` | Formatted package details |
| `pkgs upgrade` | Manager-specific upgrade |
| `pkgs refresh` | Refresh APT/DNF/XBPS repository metadata |
| `pkgs managers` | Detected managers, scope and catalog capabilities |
| `pkgs doctor` | Environment, Python, fzf, and completion diagnostics |
| `pkgs cache clear` | Clear pkgs catalogs only |

Options can go before or after the subcommand. Human-readable output is the
default. JSON is opt-in for `list`, `info`, `managers`, `doctor`, and
`completion SHELL status`.

**Exact names and queries are separate.** `install git` installs `git`;
`install --query git` opens a picker. Name arguments are validated and passed as
separate subprocess arguments, never interpolated into shell commands.
Version specifications, package URLs, local install paths, arbitrary backend
options and shell aliases for managers are outside this first release.

Transactions print the selected manager, scope, and command, then ask
`Proceed? [y/N]`. The manager can also ask its own questions. `--yes` skips the
pkgs prompt and supplies the backend's supported noninteractive flag where
available; some managers can still prompt. `--dry-run` prints the transaction
without running it. Passing names bypasses the picker, not confirmation.

## Picker and readable preview

| Key | Action |
|---|---|
| Tab / Shift-Tab | Select multiple packages and move |
| Enter | Accept selected packages, or highlighted package |
| Ctrl-X | Hide/show preview |
| Alt-I | Hide/show manager-installed packages |
| Alt-O | Open the highlighted package's HTTP(S) homepage |
| Esc / Ctrl-C | Cancel without changing packages |

The preview is visible by default, below the results. It has a purple package
heading, cyan section headings and labels, green installed state, amber external
command evidence, and dim supporting text. Description and metadata wrap to the
preview width. Sections show manager/scope, versions, description, external
commands, package details, and links. Absent fields are omitted.

Use `--preview 'right:55%:wrap'` for a wide terminal, or
`--preview 'bottom:hidden:55%:wrap'` to start hidden. The renderer strips terminal
control characters from package metadata. It does not depend on bat or alter
BAT_THEME. ANSI colors use terminal palette colors, so they suit your theme.

`--color auto` respects `NO_COLOR`; `--color never` disables colors;
`--color always` explicitly enables them. FZF_DEFAULT_OPTS and
FZF_DEFAULT_OPTS_FILE are inherited, including your colors. pkgs sets its own
record layout, preview, selection keys and output protocol. Options that alter
fzf's returned records (for example `--accept-nth`), `--filter`, or custom
accept/reload bindings are not compatible defaults for this picker.

Alt-O prefers `termux-open-url`, then `termux-open` in Termux. Elsewhere it uses
macOS `open`, `wslview`, `xdg-open`, or `gio open`, as available. The executable
receives the URL as one argument. URL-opening results and errors appear in the
preview. No homepage means a readable notice; no guessed command execution.
Registry previews may fetch metadata from the selected registry.

### Markers and external commands

- `[i]`: installed in the selected manager and scope.
- `[e]`: related executable found outside the selected system database's ownership.
- `[i][e]`: installed package plus an unowned executable copy.
- Blank: not recorded as installed; no cached external evidence is available.

The picker opens using inventory and a fresh installed database query. It does
not scan ownership for the entire catalog. Highlighting a package displays
basic information immediately, then enriches its preview with metadata and
external evidence within five seconds. Initial rows and `list` use valid cached
`[e]` evidence; fresh evidence appears in the preview and on later picker opens.
A blank marker does not mean an exhaustive external check was performed.

APT and standard pacman database fingerprints permit persistent evidence reuse;
other layouts use preview-session reuse only. Database, executable, symlink,
PATH-directory or mapping changes invalidate reusable evidence, as does TTL.

For example, `~/.fzf/bin/fzf` can be detected even if APT does not own it.
Preview evidence includes path, resolved path where relevant, PATH order,
ownership, and whether the association uses a known mapping or a same-name
candidate. `ripgrep` → `rg` is a known mapping. Same-name matches are not proof
of package identity. This is a best-effort executable check, not a complete
inventory of source builds, shell functions, aliases, libraries, or containers.
Ownership-query failures do not become external markers.

External-command detection applies to system-manager inventories. Uninstall
still includes only packages that the selected manager owns. Your source-built
executables never become APT removal targets because they were detected.

## Managers and scope

| Manager | Inventory/search | Scope and transactions |
|---|---|---|
| APT | Local apt-cache + dpkg status | System; sudo when non-root |
| pacman | Local synchronized database | System; sudo when non-root |
| paru / yay | Repo catalog; queried AUR search | Helper handles privileges |
| DNF 4/5 | Cached repoquery + rpm | System; sudo when non-root |
| XBPS | Local repository metadata + installed database | System; sudo when non-root |
| npm | Explicit registry search + cached candidates | Current project unless `--global` |
| uv-tool | Exact PyPI name lookup + cached candidates | uv isolated tool environments |
| pip | Exact PyPI name lookup + cached candidates | Python interpreter running pkgs |
| gem | Explicit remote search + cached candidates | Active RubyGems environment |

Termux is detected before Linux distribution detection. Its configured package
backend, official setup helper, and database paths are checked. The backend
reads metadata; `pkg` performs supported transactions. No sudo is added in
Termux. Pacman-backed pkg gets `--noconfirm`, not APT's `-y`, when requested.
Termux's native pkg removal can remove dependencies; read the transaction
summary produced by your installed backend.

Outside Termux, ID and ID_LIKE in /etc/os-release select the default and the
required tools are verified. APT, Arch derivatives, Fedora/RHEL derivatives,
and Void are supported. Explicit `--manager` overrides detection. On Arch with
a query, auto selection prefers paru then yay when present. Pick `--manager
pacman` to keep the operation in official repositories.

```sh
pkgs install --manager npm --global --query typescript
pkgs uninstall --manager npm --global
pkgs install --manager uv-tool ruff
pkgs install --manager pip --query requests
pkgs list --manager pip --installed
pkgs install --manager gem --query rake
```

There is no full-registry listing for npm, RubyGems, or PyPI. Start with
`--query`, or pass exact names. Python queries are exact-name metadata lookups,
not a replacement for the retired pip search service. The resulting candidates
are cached for subsequent pickers/completion. AUR searches also need a query;
without one, previously cached candidates or repository packages are shown.

System catalogs use local metadata. Refresh repository metadata first if it
is absent. DNF 4 may require its repoquery plugin. Use `pkgs upgrade` with
pacman rather than refreshing its sync database separately. pip requires names
for upgrade; pkgs does not bypass externally managed Python protections or use
sudo for language managers. Activating a venv changes the Python resolved by
the launcher, and therefore the pip environment. Check `pkgs doctor`.

## Completion

```sh
pkgs completion bash                 # Print generated script
pkgs completion zsh install --directory "$PREFIX/share/zsh/site-functions"
pkgs completion zsh update           # Update the recorded destination
pkgs completion ZSH --install         # Alias; shell names are case-insensitive
pkgs completion fish install
pkgs completion zsh status --json
pkgs completion zsh uninstall
```

Zsh chooses an explicit directory, its recorded managed destination, or the
first writable absolute directory in caller-supplied `FPATH`. An earlier
conflicting `_pkgs` is reported. No `~/.local/share/zsh/site-functions` fallback
is assumed active. From Zsh, `FPATH="$FPATH" pkgs completion zsh install` supplies
the live search path without a persistent environment change.

Bash uses the recorded destination or an installed bash-completion loader's
user autoload convention: `$BASH_COMPLETION_USER_DIR/completions`, otherwise
`${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions`. Multiple
user directories are checked in order. Without a recognized loader, automatic
setup fails; an explicit directory still permits file-only installation with
an activation warning. Finding a loader does not prove the current Bash has
loaded it. No shell startup files are sourced for discovery.

The main installer accepts repeatable `--completion-dir SHELL=DIR` overrides;
the completion command accepts `--directory DIR`. Status reports file content,
version, resolution source, loader evidence, and activation separately. A child
process cannot verify or activate its parent's live completion state.

Managed paths and content hashes are recorded in
`${XDG_STATE_HOME:-$HOME/.local/state}/pkgs/completions.json`. Keep that state
location when changing data/configuration directories, so update and uninstall
can find earlier destinations. Repeated installation makes no content changes
or extra backups when current. Foreign files, edited completions, and completion
symlinks are not overwritten.

On upgrading from 0.1.0, exact generated Bash/Zsh startup blocks are removed.
The resolved startup-file target is backed up first; symlinks, permissions, and
surrounding bytes are preserved. Edited, duplicate, or malformed blocks require
manual review and prevent that shell's migration. Only exact known legacy
completion files are retired after publishing their replacement; unrelated old
files are retained with notices. Migration respects ZDOTDIR and recorded paths.
Fish retains its managed startup block and binding behavior.

`pkgs <Tab>` completes commands/options. `pkgs install <Tab>` offers available
candidates; `pkgs uninstall <Tab>` offers only installed packages. Selecting
one or more packages inserts quoted names. **Completion does not run a
transaction.** Already-entered package names are excluded.

Bash uses a command-specific completion function, without replacing global
Readline bindings. Zsh supplies native descriptions to an existing fzf-tab
plugin; without it, the command completion invokes fzf directly. fzf-tab's own
preview configuration and selection keys remain under your control; the pkgs
picker preview/Alt-O binding belongs to the bundled picker. Fish installs a
Tab dispatcher for pkgs and retains the previous binding's commands for other
input. Fish integration is reapplied at the next prompt after sourcing.

Set `PKGS_FUZZY_TAB=0` to use native completion only. For Bash/Zsh:

```sh
export PKGS_FUZZY_TAB=0
```

For Fish: `set -gx PKGS_FUZZY_TAB 0`. If set after the binding is installed,
the dispatcher falls back to the prior binding. Completion reads local catalogs
and caches only; it never issues a registry search or package transaction.
Native candidate generation has a 1.5-second local-query budget. A failed or
slow query produces no candidates and a nonzero helper status; `PKGS_DEBUG=1`
adds stderr diagnostics. It never falls back to stale uninstall candidates. Preview requests
inside a fuzzy completion picker may fetch registry details, just like the
ordinary picker, and Alt-O opens a URL only on your keypress.

## Configuration

Optional file: `${XDG_CONFIG_HOME:-$HOME/.config}/pkgs/config.json`.
Copy `config.example.json` there and edit it. There are no mandatory config files.

```json
{
  "manager": "auto",
  "preview": "bottom:55%:wrap",
  "color": "auto",
  "cache_seconds": 300,
  "external_detection": true,
  "commands": {"fzf": ["fzf"], "ripgrep": ["rg"]}
}
```

Command mappings merge with defaults. CLI flags override configuration. Cached
catalogs live in `${XDG_CACHE_HOME:-$HOME/.cache}/pkgs`; installed state is read
fresh, and attempted transactions invalidate that scope's catalog and external
evidence. `external_detection: false` disables optional evidence checks.

Use `pkgs --debug install --dry-run` to see phase timings on stderr. Preparation
has a 45-second read-only query budget, previews five seconds, and each ownership
query at most three seconds within the preview budget. Slow foreground work
prints a delayed stderr progress notice. Query failures are distinct from empty
catalogs and cancellation. Interactive package transactions have no artificial
timeout and retain their native prompts.

Picker helpers use a controlled noninteractive Bash child rather than invoking
your interactive startup configuration. The user environment and fzf settings
are not rewritten. `--filter` and output-transforming defaults are rejected;
colors and compatible preferences remain inherited.

## Upgrade and uninstall

Extract a newer release and run its `./install.sh`. Completion content updates
along with the application. Previous application installations are kept beside
`lib/pkgs` as timestamped backups; remove those backups manually when no longer
needed. Startup backups are also retained for recovery.

```sh
./uninstall.sh --dry-run
./uninstall.sh
# Supply the same --prefix used for installation when nondefault.
```

Uninstall removes only the managed application, its links and tracked shell
integration. User configuration, caches, and backups are retained. Reload your
shell afterward. `--no-completions` also applies to uninstall if you deliberately
want to retain shell integration for another installation.

## Validation and platform limits

```sh
python3 -m unittest discover -s tests -v
bash -n pkgs install.sh uninstall.sh completions/pkgs.bash
zsh -n completions/pkgs.zsh
fish -n completions/pkgs.fish
```

Validation includes mocked-manager regressions, isolated install/reinstall/uninstall
with paths containing spaces, Bash/Zsh native completion, and Bash/Zsh/Fish
syntax checks. Real source-built fzf 0.74.5 was exercised in Termux PTYs for
selection, metadata, defaults/options files, and cancellation during slow
previews. Termux APT was queried read-only; no host package transactions ran.

The user's live Zsh/fzf-tab session, Fish interactive bindings, URL handlers,
older fzf binaries, and other Linux devices still need acceptance testing.
Fixture coverage is not real-device coverage. See `docs/TESTING.md` and
`docs/VALIDATION.json` for the checked environment and results. Native
Windows/PowerShell and Homebrew adapters are outside this release.

## Project layout

`pkgs` and `main.py` are entry points. `pkgs_lib/` contains detection, backend
adapters, catalog/cache logic, preview/picker, completion management, and CLI
routing. `completions/` holds versioned shell integrations. `tests/` is the
standard-library unittest suite. No installation commands run in tests.
