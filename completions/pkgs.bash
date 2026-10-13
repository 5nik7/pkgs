# pkgs managed completion 0.1.0
# PKGS_FUZZY_TAB=0 opts out; no global Readline binding is replaced.
_pkgs_complete() {
    local cur="${COMP_WORDS[COMP_CWORD]}" line name desc quoted joined=''
    local -a args=("${COMP_WORDS[@]:1:COMP_CWORD}")
    COMPREPLY=()
    if [[ ${PKGS_FUZZY_TAB:-1} != 0 && -t 2 && ${COMP_TYPE:-9} == 9 ]]; then
        while IFS= read -r name; do
            [[ -n "$name" ]] || continue
            printf -v quoted '%q' "$name"
            joined+="$quoted "
        done < <(command pkgs __complete --pick -- "${args[@]}")
        if [[ -n "$joined" ]]; then
            COMPREPLY=("$joined")
            compopt -o noquote -o nospace 2>/dev/null || true
        fi
    else
        while IFS=$'\t' read -r name desc; do
            [[ -n "$name" ]] && COMPREPLY+=("$name")
        done < <(command pkgs __complete -- "${args[@]}")
    fi
}
complete -F _pkgs_complete pkgs
