# pkgs 0.1.0

A fuzzy package browser and package-manager frontend for **Termux and Linux**.
Bash launcher, Python standard-library core, no pip dependencies.
The command is **`pkgs`**. It does not replace Termux's `pkg`.

## Install

Requirements: Bash 4+, Python 3.9+, and fzf 0.48+ for interactive pickers.
Native completions target Bash 4+, Zsh 5.8+, and Fish 3.6+.
Your selected package manager must already be installed.

On Termux, install any missing dependencies with your existing package manager:

```sh
pkg install python fzf
```

After extracting the release, enter its directory:

```sh
cd pkgs-0.1.0
./install.sh --dry-run
./install.sh
```

The default prefix is `~/.local`. Add `~/.local/bin` to PATH if it is not already
there. The installer installs the command, man page, and completions for shells
found on PATH. It makes managed startup blocks and backs up changed startup
files. It does not change your package installations or fetch dependencies.

```sh
# Custom prefix / install without completion setup:
./install.sh --prefix "$HOME/.local" --no-completions

pkgs --version
pkgs doctor
pkgs completion zsh status
```

Reload the relevant startup file after installation:

```sh
# Zsh (respects a custom ZDOTDIR):
source "${ZDOTDIR:-$HOME}/.zshrc"
# Bash:
source ~/.bashrc
```

In Fish, run `source ~/.config/fish/conf.d/pkgs.fish` (adjust for XDG_CONFIG_HOME),
then return to the prompt. Rebinding your Fish keys later requires calling
`__pkgs_bind_tab` again. Use `man pkgs` if your MANPATH includes the prefix.

You can also run `./pkgs` directly from the extracted source directory.

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
- Blank: not recorded as installed; no external candidate found.

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
pkgs completion zsh install          # Install/update
pkgs completion ZSH --install        # Same; shell names are case-insensitive
pkgs completion fish install
pkgs completion zsh status --json
pkgs completion zsh uninstall
```

Installation compares versioned content, updates managed files, adds one
identifiable startup block, and backs up changes. It respects XDG paths and
ZDOTDIR. Foreign completion files are never overwritten. A child process cannot
reload your current shell, so the command prints the source/reload instruction.

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
Cold system completion may spend time loading local metadata. Preview requests
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
fresh, and attempted transactions invalidate that scope's cached catalog.
Disable external detection if ownership queries make a large inventory slow.

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
```

The release was checked with mocked manager data and fake fzf subprocesses:
installed-state filtering, backend parsing, command arrays, cancellation,
nonzero exits, stale-cache invalidation, URL validation, color/width behavior,
completion insertion data, and repeatable completion setup. Installer,
reinstallation and removal were exercised in an isolated home with a prefix
containing spaces. Bash and Zsh syntax/native candidates were checked here.

A real fzf UI, Fish shell, Termux device and non-APT Linux hosts were not
available in the build environment. Those interactive/platform paths still
need on-device verification. Native Windows/PowerShell and Homebrew adapters
are not part of this release. See docs/TESTING.md for a short device checklist.

## Project layout

`pkgs` and `main.py` are entry points. `pkgs_lib/` contains detection, backend
adapters, catalog/cache logic, preview/picker, completion management, and CLI
routing. `completions/` holds versioned shell integrations. `tests/` is the
standard-library unittest suite. No installation commands run in tests.
