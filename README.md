# pkgs 0.1.1

A fuzzy package browser and package-manager frontend for **Termux and Linux**.
Browse packages with fzf, inspect their metadata, and install or remove selections
through your chosen manager. Human-readable, colorized output is the default;
use `--json` for supported structured reports.

pkgs uses a Bash launcher and a Python standard-library core, with no pip
dependencies. The command is **`pkgs`**; Termux's `pkg` remains its native frontend.

[Quick start](#quick-start) · [Installation](#installation) ·
[Commands](#commands) · [Picker](#picker-and-preview) ·
[Managers](#supported-managers-and-scope) · [Completion](#completion) ·
[Configuration](#configuration) · [Troubleshooting](#troubleshooting) ·
[Upgrade and uninstall](#upgrade-and-uninstall) · [Validation](#validation-and-platform-limits)

## Quick start

Requirements: Bash 4+, Python 3.9+, and an installed supported package manager.
Interactive pickers also require fzf 0.48+. Native completions target Bash 4+,
Zsh 5.8+, and Fish 3.6+.

From the root of a checkout or extracted source directory:

```sh
./pkgs --help
./pkgs search editor
./pkgs install --query editor --dry-run
```

`search` opens a read-only picker; Enter prints details for your selections.
The install example lets you select packages and prints the planned transaction
without running it. Remove `--dry-run` when ready to install; pkgs asks for
confirmation before invoking the manager.

Use `./pkgs` to run this checkout directly. After installation, use `pkgs` when
the installation's `bin` directory is on PATH. Examples below use that installed
command; substitute `./pkgs` when working from the checkout.

## Installation

The installer does not fetch dependencies or install packages through a manager.
pkgs uses the first fzf on PATH, falling back to `~/.fzf/bin/fzf` for existing
source installations. `pkgs doctor` reports the resolved executable and version.

From the source directory, preview installation before applying it:

```sh
./install.sh --dry-run
./install.sh
```

The default application prefix is `~/.local`. Installation creates the command
at `~/.local/bin/pkgs`, the application under `~/.local/lib/pkgs`, and a man page
under `~/.local/share/man/man1`. It also installs completions for shells found on
PATH. **The installer does not add the command to PATH.** Ensure your shell
includes the chosen prefix's `bin` directory, or use the absolute launcher path.
Use `man pkgs` when your man-page search path includes the prefix's `share/man`.

All completion destinations are checked before installation. If a destination
cannot be determined reliably, installation stops with override instructions.
For Zsh, run the following from your actual Zsh session to supply its live
completion search path for these invocations:

```zsh
FPATH="$FPATH" ./install.sh --dry-run
FPATH="$FPATH" ./install.sh
```

You can choose completion directories explicitly or install the application
without completion setup:

```sh
# Termux example: use only if this directory is already in Zsh's fpath.
./install.sh --completion-dir "zsh=$PREFIX/share/zsh/site-functions"

# Application-only installation; --prefix can select another location.
./install.sh --prefix "$HOME/.local" --no-completions
```

Repeat `--completion-dir SHELL=DIR` for multiple shells. Bash and Zsh setup is
file-only: it adds no startup blocks, source statements, or completion search
paths. Fish uses a managed `conf.d` integration. Follow the printed one-time
activation instructions and the [shell setup guidance](#completion) below.

## Commands

| Command | Result |
|---|---|
| `pkgs` | Usage, without starting fzf |
| `pkgs help`, `pkgs -h`, `pkgs -H`, `pkgs --help` | Usage |
| `pkgs --version`, `pkgs -V` | Version |
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
options and shell aliases for managers are not supported in 0.1.1.

Transactions print the selected manager, scope, and command, then ask
`Proceed? [y/N]`. The manager can also ask its own questions. `--yes` skips the
pkgs prompt and supplies the backend's supported noninteractive flag where
available; some managers can still prompt. `--dry-run` prints the transaction
without running it, although preparation and previews may still query metadata.
Passing names bypasses the picker, not confirmation.

## Picker and preview

| Key | Action |
|---|---|
| Tab / Shift-Tab | Toggle selection and move down/up |
| Enter | Accept selected packages, or the highlighted package |
| Ctrl-X | Hide/show preview |
| Alt-I | Hide/show manager-installed packages |
| Alt-O | Open the highlighted package's HTTP(S) homepage |
| Esc / Ctrl-C | Cancel without changing packages |

The preview appears below the results and shows available versions, description,
manager/scope, external commands, package details, and links. Text wraps to the
preview width; absent fields are omitted and terminal control characters are
stripped from metadata. Registry previews may fetch metadata.

Use `--preview 'right:55%:wrap'` for a wide terminal or
`--preview 'bottom:hidden:55%:wrap'` to start hidden. The preview uses terminal
palette colors and does not require bat or change `BAT_THEME`.

`--color auto` respects `NO_COLOR`; `--color never` disables pkgs colors;
`--color always` explicitly enables them. Your fzf colors and compatible
`FZF_DEFAULT_OPTS` / `FZF_DEFAULT_OPTS_FILE` preferences remain inherited.
pkgs controls the picker layout, selection keys, preview, and returned records;
see [troubleshooting](#troubleshooting) for incompatible defaults.

URLs open only when you press Alt-O. In Termux, pkgs prefers `termux-open-url`,
then `termux-open`; elsewhere it uses an available platform URL handler.
The URL is passed as a single argument, and results or errors appear in the
preview. A missing homepage produces a notice.

### Markers and external commands

| Marker | Meaning |
|---|---|
| `[i]` | Installed in the selected manager and scope |
| `[e]` | Related executable found outside the selected system database's ownership |
| `[i][e]` | Installed package plus an unowned executable copy |
| Blank | Not recorded as installed; no cached external evidence is available |

Installed state is read fresh. External-command checks happen lazily in previews,
without scanning ownership for the entire catalog. Initial rows and `list` use
valid cached evidence; new evidence appears in the preview and on later picker
opens. A blank marker does not mean an exhaustive external check was performed.

For example, pkgs can detect `~/.fzf/bin/fzf` even when APT does not own it.
The preview identifies paths, ownership, and whether an association comes from
a known mapping such as `ripgrep` → `rg` or a same-name candidate. Same-name
matches do not prove package identity, and failed ownership queries do not
produce external markers.

This is a best-effort check for system-manager inventories, not a complete
inventory of source builds, aliases, functions, libraries, or containers.
**Uninstall candidates always come from the selected manager's installed
database.** Detecting a source-built executable never makes it a removal target.

## Supported managers and scope

| Manager | Inventory/search | Scope and transactions |
|---|---|---|
| APT | Local apt-cache + dpkg status | System; sudo when non-root outside Termux |
| pacman | Local synchronized database | System; sudo when non-root outside Termux |
| paru / yay | Repo catalog; queried AUR search | Helper handles privileges |
| DNF 4/5 | Cached repoquery + rpm | System; sudo when non-root outside Termux |
| XBPS | Local repository metadata + installed database | System; sudo when non-root outside Termux |
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
a query, auto selection prefers paru then yay when present. Pick
`--manager pacman` to keep the operation in official repositories.

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

`pkgs <Tab>` completes commands and options. `pkgs install <Tab>` offers available
candidates; `pkgs uninstall <Tab>` offers only installed packages. Selecting
packages inserts quoted names and excludes names already entered.
**Completion never runs package transactions or registry searches.** Candidates
come from local catalogs and caches; previews inside a fuzzy picker may fetch
registry metadata, and Alt-O opens a URL only on your keypress.

### Bash

```bash
pkgs completion bash install
pkgs completion bash status
```

Bash uses an explicit `--directory DIR`, the recorded destination, or an installed
bash-completion loader's user autoload convention:
`$BASH_COMPLETION_USER_DIR/completions`, otherwise
`${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions`.
Multiple user directories are checked in order. Without a recognized loader,
automatic setup fails; an explicit directory permits file-only installation
with an activation warning.

With bash-completion loaded, a new session can autoload the file. To register it
in the current session, source the completion file at the printed destination.
Finding a loader does not prove the current shell has loaded it. pkgs uses a
command-specific completion function and preserves global Readline bindings.

### Zsh

Run from your Zsh session:

```zsh
FPATH="$FPATH" pkgs completion zsh install
FPATH="$FPATH" pkgs completion zsh status
```

Zsh chooses an explicit `--directory DIR`, its recorded managed destination, or
the first writable absolute directory in caller-supplied `FPATH`. An earlier
conflicting `_pkgs` is reported. No inactive fallback directory is assumed.
pkgs cannot inspect its parent shell's live arrays and does not launch
interactive shells or source startup files to guess them.

Verify that the destination is in `$fpath`, then use your normal completion
reload or run this once in the current shell:

```zsh
autoload -Uz compinit
compinit
autoload -Uz _pkgs
compdef _pkgs pkgs
```

With fzf-tab, pkgs supplies native descriptions and leaves that plugin's preview
and keys under your control. Without fzf-tab, package completion invokes the
bundled fzf picker directly. The bundled preview and Alt-O binding apply to that
picker, not to fzf-tab's own UI.

### Fish

```fish
pkgs completion fish install
pkgs completion fish status
```

Follow the printed activation instructions. With the default configuration
location, run `source ~/.config/fish/conf.d/pkgs.fish`, then return to the prompt;
adjust the path when using `XDG_CONFIG_HOME`.

Fish installs a Tab dispatcher for pkgs and retains the previous binding's
commands for other input. Integration is reapplied at the next prompt after
sourcing. Rebinding keys later requires `__pkgs_bind_tab` again.

### Completion management and preferences

```sh
pkgs completion bash                 # Print the generated script
pkgs completion zsh update           # Update the recorded destination
pkgs completion zsh status --json
pkgs completion zsh uninstall
```

Shell names are case-insensitive, and `completion ZSH --install` is an alias
for `completion zsh install`. The completion command accepts `--directory DIR`;
the main installer accepts repeatable `--completion-dir SHELL=DIR` overrides.
Status separates file content/version, destination discovery, loader evidence,
and activation. A child process cannot verify or activate its parent's live
completion state.

Managed paths and hashes are recorded in
`${XDG_STATE_HOME:-$HOME/.local/state}/pkgs/completions.json`. Retain that state
location when changing data/configuration directories so update and uninstall
can find earlier destinations. Repeated completion installation makes no content
changes or extra backups when current. Foreign files, edited completions, and
completion symlinks are not overwritten.

Set `PKGS_FUZZY_TAB=0` to use native completion only:

```sh
export PKGS_FUZZY_TAB=0               # Bash or Zsh
```

For Fish, use `set -gx PKGS_FUZZY_TAB 0`; an existing dispatcher falls back to its
prior binding. Native candidate generation has a 1.5-second local-query budget.
Failed or slow queries return no candidates and a nonzero helper status;
`PKGS_DEBUG=1` adds stderr diagnostics. Uninstall completion never falls back
to stale candidates.

## Configuration

Optional file: `${XDG_CONFIG_HOME:-$HOME/.config}/pkgs/config.json`.
Copy [config.example.json](config.example.json) there and edit it. There are no
mandatory config files.

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

## Troubleshooting

| Symptom | What to check |
|---|---|
| `pkgs` is missing or runs an older copy | Run `./pkgs doctor` from the checkout. In Zsh, use `whence -a pkgs fzf`; in Bash, use `type -a pkgs fzf`; in Fish, use `type -a pkgs fzf`. Check the chosen prefix's `bin` directory on PATH. |
| Completion file exists but Tab does not work | Run `pkgs completion SHELL status` with your shell name to inspect the destination and activation evidence. Follow the shell-specific setup above; file installation alone does not activate a running shell. |
| fzf reports an error or behaves unexpectedly | Inspect `FZF_DEFAULT_OPTS` and `FZF_DEFAULT_OPTS_FILE`. Output-transforming options such as `--accept-nth`, `--print`, and `--filter` are rejected; custom accept/reload bindings are incompatible. |
| Catalogs are missing or queries fail | Run `pkgs managers` and `pkgs doctor`. Check local repository metadata and registry connectivity where applicable; use the selected manager's supported refresh/upgrade flow. |
| Preparation or previews are slow | Run `pkgs --debug install --dry-run` for phase timings on stderr. Query failures are reported separately from empty results and cancellation. |

To isolate fzf defaults for one invocation from Bash or Zsh:

```sh
env -u FZF_DEFAULT_OPTS -u FZF_DEFAULT_OPTS_FILE ./pkgs install --query fzf --dry-run --debug
```

Preparation has a 45-second read-only query budget, previews five seconds, and
ownership queries at most three seconds within the preview budget. Slow
foreground work prints a delayed stderr progress notice. Interactive package
transactions retain their native prompts and have no artificial timeout.
Picker helpers run in a controlled noninteractive Bash child without sourcing
your interactive startup configuration.

See [testing and device acceptance](docs/TESTING.md) for detailed diagnostics
and isolated checks.

## Upgrade and uninstall

From a newer source checkout or extracted release, run `./install.sh` with
the same prefix and any required completion context or overrides. Completion
content updates along with the application. Previous installations are kept beside
`lib/pkgs` as timestamped backups; remove those backups manually when no longer
needed. Startup backups are also retained for recovery.

When upgrading from 0.1.0, exact generated Bash/Zsh startup blocks are removed
with backups of the resolved startup-file targets. Symlinks, permissions, and
surrounding bytes are preserved. Edited, duplicate, or malformed blocks require
manual review and prevent that shell's migration. Only exact known legacy
completion files are retired after their replacements are published; unrelated
files are retained with notices. Migration respects `ZDOTDIR` and recorded
paths. Fish retains its managed startup block and binding behavior.

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

Run the automated suite and shell syntax checks from the source directory:

```sh
python3 -m unittest discover -s tests -v
bash -n pkgs install.sh uninstall.sh completions/pkgs.bash
zsh -n completions/pkgs.zsh
fish -n completions/pkgs.fish
```

Tests mock package-manager transactions and install/reinstall/uninstall the
application only in temporary locations. They cover backend behavior,
completion, migration, and paths containing spaces. Real-fzf PTY tests use
fixture package metadata and skip when fzf is unavailable.

The checked-in [0.1.1 validation record](docs/VALIDATION.json), dated
**2026-10-13**, reports 85 passing tests on native Android/Termux with Python
3.14, Bash 5.3.20, Zsh 5.9.2, Fish 4.9.3, and source-built fzf 0.74.5.
It records shell syntax and isolated completion checks, real-fzf PTY behavior,
and separate read-only Termux APT queries. No host package transactions ran.
These are historical results, not a claim that every environment is tested.

Live Zsh/fzf-tab configuration, Fish interactive bindings, URL handlers, older
fzf binaries, and other Linux devices still need acceptance testing. Fixture
coverage is not real-device coverage. Native Windows/PowerShell and Homebrew
adapters are outside this release.

See [testing and device acceptance](docs/TESTING.md) for procedures,
[backend references](docs/SOURCES.md) for sources, and the
[changelog](CHANGELOG.md) for release changes. The [man page](docs/pkgs.1)
provides the command reference.
