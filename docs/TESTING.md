# Device acceptance checks

Start with `pkgs doctor` and confirm the default manager, Python environment,
and fzf path. Ensure the correct package scope is displayed before accepting a
transaction. The following picker checks can all be done without modifying
packages.

1. `pkgs`, `pkgs -H`, and `pkgs --version` work without launching fzf.
2. `pkgs install --dry-run` opens the picker. Ctrl-X toggles the colorized
   preview, long descriptions wrap, Tab selects multiple names, and Enter
   prints clean command arguments without installing.
3. Alt-I toggles installed visibility. Esc and Ctrl-C exit without a transaction.
4. Highlight a package with a homepage; Alt-O opens it using the device's URL
   handler. Highlight one without a homepage; the preview shows a notice.
5. `pkgs uninstall --dry-run` offers only manager-installed packages. A
   source-installed fzf may appear as [e] in the install picker, but it must not
   become an uninstall candidate unless the manager also owns the package.
6. Run completion install twice, then status. There should be one managed
   startup block. Reload the shell and try `pkgs install <Tab>` and
   `pkgs uninstall <Tab>`. Selections must insert names without running them.
7. With Zsh fzf-tab, verify that no nested fuzzy menu appears. With Bash/Fish,
   also check that completion for another command still behaves normally.
8. Try npm global versus project scope and an active Python virtual environment.
   Inspect the displayed scope and dry-run command before doing a real install.
9. Set NO_COLOR or --color never: output and previews should contain no ANSI
   colors. Keep your ordinary FZF_DEFAULT_OPTS colors to verify inheritance.
10. After these read-only checks, perform one intentional install/uninstall of
    a disposable package on each manager you intend to use.

The automated suite uses fixtures and mocks; it does not certify every package
manager release, package database, custom shell binding, or terminal emulator.
