#!/bin/sh
# Fail-closed launcher for block-dangerous-commands.py.
#
# The stdout-contract CLIs (Antigravity, Copilot) block only when the hook
# prints a deny payload; "no output" means allow. So a hook that cannot even
# start silently disables protection for them -- and Antigravity's delegated
# invocations pass --dangerously-skip-permissions, making the hook its only
# gate. This launcher denies when the interpreter or the hook script is
# unavailable, instead of letting the operation through.
#
# It checks preconditions rather than the hook's exit status on purpose: the
# hook itself exits 2 on its own fail-closed path, which is indistinguishable
# from "python3 could not find the file". Branching on exit status would emit
# a second deny payload after the hook's own, producing two JSON objects on
# stdout.
#
# POSIX sh only -- macOS CI runs bash 3.2 and this must not depend on bash 4+.

set -u

HOOK_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HOOK="$HOOK_DIR/block-dangerous-commands.py"

if command -v python3 >/dev/null 2>&1 && [ -r "$HOOK" ]; then
    exec python3 "$HOOK"
fi

REASON="the dangerous-command hook could not start (missing python3 or $HOOK)"
MANUAL="Blocked: $REASON. If intentional, ask the user to run it manually."

# Emit every deny contract at once: the caller is unknown at this point.
printf '{"decision":"deny","reason":"%s","permissionDecision":"deny","permissionDecisionReason":"%s"}\n' \
    "$MANUAL" "$MANUAL"
printf 'BLOCKED: %s\n' "$MANUAL" >&2
exit 2
