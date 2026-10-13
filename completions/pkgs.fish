# pkgs managed completion 0.1.0
function __pkgs_candidates
    set -l words (commandline -opc)
    set -e words[1]
    command pkgs __complete -- $words (commandline -ct)
end
complete -c pkgs -e
complete -c pkgs -f -a '(__pkgs_candidates)'
function __pkgs_tab
    set -l words (commandline -opc)
    if test "$words[1]" = pkgs; and test "$PKGS_FUZZY_TAB" != 0
        set -e words[1]
        set -l selected (command pkgs __complete --pick -- $words (commandline -ct))
        if test (count $selected) -gt 0
            set -l escaped (string escape -- $selected)
            commandline -rt -- (string join ' ' -- $escaped)' '
        end
        commandline -f repaint
    else
        set -l variable __pkgs_old_tab_$fish_bind_mode
        set -l saved $$variable
        if test (count $saved) -eq 0
            commandline -f complete
        else
            set -l input_functions (bind --function-names)
            for action in $saved
                if contains -- $action $input_functions
                    commandline -f $action
                else
                    # These commands came from the user's existing, trusted key binding.
                    eval $action
                end
            end
        end
        set -l mode_variable __pkgs_old_mode_$fish_bind_mode
        if set -q $mode_variable
            set fish_bind_mode $$mode_variable
        end
    end
end
function __pkgs_bind_tab
    for mode in default insert
        set -l old (bind --user -M $mode \t 2>/dev/null)
        if test (count $old) -eq 0
            set old (bind --preset -M $mode \t 2>/dev/null)
        end
        if string match -q '*__pkgs_tab*' -- "$old"
            continue
        end
        set -l tokens
        printf '%s\n' "$old" | read --tokenize --array tokens
        if test "$tokens[1]" = bind
            set -e tokens[1]
            while test (count $tokens) -gt 0
                switch $tokens[1]
                    case -M --mode
                        set -e tokens[1..2]
                    case -m --sets-mode
                        set -g __pkgs_old_mode_$mode $tokens[2]
                        set -e tokens[1..2]
                    case '--*' '-*'
                        set -e tokens[1]
                    case '*'
                        # First remaining word is the key; remaining words are commands.
                        set -e tokens[1]
                        break
                end
            end
            set -g __pkgs_old_tab_$mode $tokens
        end
        bind -M $mode \t __pkgs_tab
    end
end

if status is-interactive; and test "$PKGS_FUZZY_TAB" != 0
    # Delay until fish has installed its normal key bindings.
    function __pkgs_first_prompt --on-event fish_prompt
        __pkgs_bind_tab
        functions -e __pkgs_first_prompt
    end
end
