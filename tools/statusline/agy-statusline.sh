#!/bin/bash

# Antigravity CLI (agy) statusline script.
#
# Renders Claude-parity project context — directory, venv, Python version, git
# branch + status, and GitHub user — computed LOCALLY (agy's JSON payload does
# not carry these; it only reports `vcs.type`). agy-native fields (model,
# context window, agent state, quota, sandbox) come from the stdin JSON.
# See docs/development/ai/statusline.md.
#
# Color theme: gray, orange, blue, teal, green, lavender, rose, gold, slate, cyan
COLOR="blue"

# Color codes (identical palette to .claude/statusline-command.sh for visual parity)
C_RESET='\033[0m'
C_GRAY='\033[38;5;245m'  # explicit gray for default text
C_BAR_EMPTY='\033[38;5;238m'
C_DIM="$C_BAR_EMPTY"  # dim separators
C_PCT='\033[38;5;71m'  # green: percentage values in quota segment
C_TIME='\033[38;5;136m'  # gold: reserved for time values
C_ROSE='\033[38;5;132m'  # rose: error agent-state (fixed, not theme-dependent)
case "$COLOR" in
    orange)   C_ACCENT='\033[38;5;173m' ;;
    blue)     C_ACCENT='\033[38;5;74m' ;;
    teal)     C_ACCENT='\033[38;5;66m' ;;
    green)    C_ACCENT='\033[38;5;71m' ;;
    lavender) C_ACCENT='\033[38;5;139m' ;;
    rose)     C_ACCENT='\033[38;5;132m' ;;
    gold)     C_ACCENT='\033[38;5;136m' ;;
    slate)    C_ACCENT='\033[38;5;60m' ;;
    cyan)     C_ACCENT='\033[38;5;37m' ;;
    *)        C_ACCENT="$C_GRAY" ;;
esac

command -v jq >/dev/null 2>&1 || { printf 'statusline: jq not installed (run: doit install_jq)\n'; exit 0; }

input=$(cat)

# Extract agy-native fields in one jq pass; fall back to defaults on missing/invalid JSON.
# The last three fields feed the opt-in quota segment (AGY_STATUSLINE_EXTRAS).
#
# Populate the array with a `while read` loop rather than `mapfile`: `mapfile`
# is a bash 4+ builtin, and macOS ships bash 3.2 by default. Process
# substitution keeps the loop in this shell so the array persists. jq emits one
# newline-terminated line per field (empty fields become empty lines), so the
# array always has the same nine elements read positionally below.
_fields=()
while IFS= read -r _line; do
    _fields+=("$_line")
done < <(
    printf '%s' "$input" | jq -r '
        (.workspace.current_dir // .cwd // ""),
        (.model.display_name // .model.id // "?"),
        (.agent_state // "idle"),
        ((.context_window.context_window_size // 0) | tostring),
        (((.context_window.current_usage.input_tokens // 0)
          + (.context_window.current_usage.cache_read_input_tokens // 0)
          + (.context_window.current_usage.cache_creation_input_tokens // 0)) | tostring),
        ((.context_window.used_percentage // 0) | tostring),
        ((.sandbox.enabled // false) | tostring),
        ((.quota["gemini-5h"].remaining_fraction // -1) | tostring),
        ((.quota["gemini-weekly"].remaining_fraction // -1) | tostring)
    ' 2>/dev/null
)

cwd="${_fields[0]:-}"
model="${_fields[1]:-?}"
agent_state="${_fields[2]:-idle}"
ctx_size="${_fields[3]:-0}"
ctx_used_tokens="${_fields[4]:-0}"
used_pct_raw="${_fields[5]:-0}"
sandbox_enabled="${_fields[6]:-false}"
q5h_frac="${_fields[7]:--1}"
qwk_frac="${_fields[8]:--1}"

# Anchor the working directory: agy's payload cwd, else the script's own PWD
# (agy runs the statusline command from the workspace root).
[[ -z "$cwd" || ! -d "$cwd" ]] && cwd="$PWD"

# --- Directory (package name) ---
dir=$(basename "$cwd" 2>/dev/null || echo "?")

# --- Python virtual environment ---
venv_name=""
if [[ -n "$VIRTUAL_ENV_PROMPT" ]]; then
    venv_name="$VIRTUAL_ENV_PROMPT"
elif [[ -n "$VIRTUAL_ENV" ]]; then
    venv_name="$(basename "$VIRTUAL_ENV")"
fi

# --- Active Python version ---
python_version=$(python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>/dev/null || echo "")

# --- GitHub username (optional) ---
# `gh api` writes the HTTP error body to stdout on failure (only the summary
# line goes to stderr), so clear the capture on non-zero exit — `|| echo ""`
# would append to the error body instead of replacing it.
gh_user=$(gh api user --jq ".login" 2>/dev/null) || gh_user=""

# --- Git branch, uncommitted count, and sync status (computed locally) ---
branch=""
git_status=""
if [[ -n "$cwd" && -d "$cwd" ]]; then
    branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
    if [[ -n "$branch" ]]; then
        file_count=$(git -C "$cwd" --no-optional-locks status --porcelain -uall 2>/dev/null | wc -l | tr -d ' ')

        sync_status=""
        upstream=$(git -C "$cwd" rev-parse --abbrev-ref @{upstream} 2>/dev/null)
        if [[ -n "$upstream" ]]; then
            fetch_head="$cwd/.git/FETCH_HEAD"
            fetch_ago=""
            if [[ -f "$fetch_head" ]]; then
                # GNU `stat -f` means "filesystem status": it exits 1 but still prints
                # filesystem info to stdout, so `stat -f ... || stat -c ...` captures
                # both. Probe for BSD stat first, then run exactly one form.
                if stat -f %m "$fetch_head" >/dev/null 2>&1; then
                    fetch_time=$(stat -f %m "$fetch_head" 2>/dev/null)
                else
                    fetch_time=$(stat -c %Y "$fetch_head" 2>/dev/null)
                fi
                if [[ -n "$fetch_time" ]]; then
                    now=$(date +%s)
                    diff=$((now - fetch_time))
                    if [[ $diff -lt 60 ]]; then
                        fetch_ago="<1m ago"
                    elif [[ $diff -lt 3600 ]]; then
                        fetch_ago="$((diff / 60))m ago"
                    elif [[ $diff -lt 86400 ]]; then
                        fetch_ago="$((diff / 3600))h ago"
                    else
                        fetch_ago="$((diff / 86400))d ago"
                    fi
                fi
            fi

            counts=$(git -C "$cwd" rev-list --left-right --count HEAD...@{upstream} 2>/dev/null)
            ahead=$(echo "$counts" | cut -f1)
            behind=$(echo "$counts" | cut -f2)
            if [[ "$ahead" -eq 0 && "$behind" -eq 0 ]]; then
                if [[ -n "$fetch_ago" ]]; then
                    sync_status="synced ${fetch_ago}"
                else
                    sync_status="synced"
                fi
            elif [[ "$ahead" -gt 0 && "$behind" -eq 0 ]]; then
                sync_status="${ahead} ahead"
            elif [[ "$ahead" -eq 0 && "$behind" -gt 0 ]]; then
                sync_status="${behind} behind"
            else
                sync_status="${ahead} ahead, ${behind} behind"
            fi
        else
            sync_status="no upstream"
        fi

        if [[ "$file_count" -eq 0 ]]; then
            git_status="(0 files uncommitted, ${sync_status})"
        elif [[ "$file_count" -eq 1 ]]; then
            single_file=$(git -C "$cwd" --no-optional-locks status --porcelain -uall 2>/dev/null | head -1 | sed 's/^...//')
            git_status="(${single_file} uncommitted, ${sync_status})"
        else
            git_status="(${file_count} files uncommitted, ${sync_status})"
        fi
    fi
fi

# --- Agent state (agy-specific): colored dot + label ---
case "$agent_state" in
    working|running|thinking|busy|active) state_color="$C_ACCENT" ;;
    error|failed)                         state_color="$C_ROSE" ;;
    *)                                    state_color="$C_GRAY" ;;
esac

# --- Context bar: prefer real token occupancy, else agy's used_percentage ---
if [[ "$ctx_size" -gt 0 && "$ctx_used_tokens" -gt 0 ]]; then
    pct=$((ctx_used_tokens * 100 / ctx_size))
elif [[ "$used_pct_raw" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    pct="${used_pct_raw%%.*}"
else
    pct=0
fi
[[ $pct -gt 100 ]] && pct=100
[[ $pct -lt 0 ]] && pct=0

bar=""
for ((i=0; i<10; i++)); do
    bar_start=$((i * 10))
    progress=$((pct - bar_start))
    if [[ $progress -ge 8 ]]; then
        bar+="${C_ACCENT}█${C_RESET}"
    elif [[ $progress -ge 3 ]]; then
        bar+="${C_ACCENT}▄${C_RESET}"
    else
        bar+="${C_BAR_EMPTY}░${C_RESET}"
    fi
done
ctx="${bar} ${C_GRAY}${pct}%"
[[ "$ctx_size" -gt 0 ]] && ctx+=" of $((ctx_size / 1000))k tokens"

# --- Build output (three lines, mirroring the Claude statusline) ---
# Line 1: 📁 dir | 🐍 venv | Python: version
line1="📁 ${dir}"
[[ -n "$venv_name" ]] && line1+=" | 🐍 ${venv_name}"
[[ -n "$python_version" ]] && line1+=" | Python: ${python_version}"

# Line 2: @user | 🔀 branch (git status) | ● state
line2=""
[[ -n "$gh_user" ]] && line2+="@${gh_user}"
if [[ -n "$branch" ]]; then
    [[ -n "$line2" ]] && line2+=" | "
    line2+="🔀 ${branch} ${git_status}"
fi
[[ -n "$line2" ]] && line2+=" | "
line2+="${state_color}●${C_RESET} ${state_color}${agent_state}${C_RESET}"

# Line 3: model | context bar [| quota extras]
line3="${C_ACCENT}${model}${C_GRAY} | ${ctx}${C_RESET}"

# Opt-in quota segment (agy-native), gated by AGY_STATUSLINE_EXTRAS.
# Mirrors CLAUDE_USAGE_STATUSLINE: base render unchanged; this only appends.
# See docs/development/ai/statusline.md#opt-in-quota-display
if [[ -n "$AGY_STATUSLINE_EXTRAS" ]]; then
    seg=""
    if [[ "$q5h_frac" != "-1" ]]; then
        used5=$(awk -v f="$q5h_frac" 'BEGIN { printf "%.0f", (1 - f) * 100 }')
        seg+="${C_ACCENT}5h:${C_PCT}${used5}%${C_RESET}"
    fi
    if [[ "$qwk_frac" != "-1" ]]; then
        usedw=$(awk -v f="$qwk_frac" 'BEGIN { printf "%.0f", (1 - f) * 100 }')
        [[ -n "$seg" ]] && seg+="${C_GRAY} · "
        seg+="${C_ACCENT}wk:${C_PCT}${usedw}%${C_RESET}"
    fi
    if [[ "$sandbox_enabled" == "true" ]]; then
        [[ -n "$seg" ]] && seg+="${C_GRAY} · "
        seg+="🔒"
    fi
    [[ -n "$seg" ]] && line3+="${C_GRAY} | ${seg}${C_RESET}"
fi

printf '%b\n' "$line1"
printf '%b\n' "$line2"
printf '%b\n' "$line3"
