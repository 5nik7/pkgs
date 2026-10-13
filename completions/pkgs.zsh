#compdef pkgs
# pkgs managed completion 0.1.0
local -a values descriptions selected args
local line name desc
args=("${(@)words[2,CURRENT]}")
# fzf-tab uses native candidates/descriptions. Do not nest a second picker.
if [[ ${PKGS_FUZZY_TAB:-1} != 0 && -t 2 ]] &&
   (( ! ${+functions[_fzf_tab]} && ! ${+functions[fzf-tab-complete]} )); then
    selected=("${(@f)$(command pkgs __complete --pick -- "${args[@]}")}")
    selected=("${(@)selected:#}")
    if (( ${#selected} )); then
        local joined="${(j: :)${(q)selected}}"
        compadd -U -Q -- "$joined"
    fi
else
    while IFS=$'\t' read -r name desc; do
        [[ -n "$name" ]] || continue
        values+=("$name")
        descriptions+=("$name — $desc")
    done < <(command pkgs __complete -- "${args[@]}")
    compadd -U -d descriptions -- "${values[@]}"
fi
