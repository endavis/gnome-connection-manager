#!/usr/bin/env bash
# Installs Gnome Connection Manager from its git repository, and updates it (#294):
#
#   wget -qO- https://raw.githubusercontent.com/endavis/gnome-connection-manager/main/install.sh | bash
#
# wget, since a new Ubuntu desktop has it and not curl; `curl -fsSL` does the same.
#
# The clone is ~/.local/share/gnome-connection-manager/repo, each version installed is a
# worktree of it under versions/, and the link `current` names the one in use. An update
# adds a worktree and moves the link, and never changes a version's files: a running GCM
# reads its glade file again for every dialog and runs ssh.expect for each tab, so it must
# keep the files it started with. The launcher, ~/.local/bin/gnome-connection-manager,
# resolves `current` once as GCM starts, and holds a shared lock on that version while GCM
# runs. An update keeps the version it replaces, and removes older ones nothing holds.
#
# Arguments, after `bash -s --` when the script is piped:
#
#   release      the newest release, a vX.Y.Z tag: the default
#   main         the tip of main, each change as it merges
#   vX.Y.Z       that release
#   --uninstall  remove GCM, keeping its configuration and the packages apt installed
#
# `release` and `main` are remembered, so a run given neither follows the last one given.
# GCM_REPO_URL installs from another repository, such as a fork or a test's.
#
# apt installs the packages the version's .deb depends on and recommends, and git. Those
# it suggests, GCM's optional programs, it installs too if the person running this says
# so, asked once for all of them.
#
# Everything is done in functions called from the script's last line, so a download cut
# short runs nothing, and nothing the script runs can read the rest of it as its input,
# which it is when piped.

set -euo pipefail

REPO_URL=${GCM_REPO_URL:-https://github.com/endavis/gnome-connection-manager.git}
MARKER="Written by GCM's install.sh"

say() { printf '%s\n' "$*"; }

die() {
    printf 'install.sh: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Installs Gnome Connection Manager, or updates it when run again.

  install.sh [release | main | vX.Y.Z]
  install.sh --uninstall

  release      the newest release: the default
  main         the tip of main, each change as it merges
  vX.Y.Z       that release
  --uninstall  remove GCM, keeping its configuration and the packages apt installed

Piped to bash, give them after `bash -s --`.
EOF
}

set_paths() {
    local data_home=${XDG_DATA_HOME:-} path
    # A relative XDG_DATA_HOME is to be ignored, the XDG spec says.
    [[ $data_home == /* ]] || data_home=$HOME/.local/share
    GCM_HOME=$data_home/gnome-connection-manager
    REPO=$GCM_HOME/repo
    VERSIONS=$GCM_HOME/versions
    LAUNCHER=$HOME/.local/bin/gnome-connection-manager
    DESKTOP_ENTRY=$data_home/applications/gnome-connection-manager.desktop
    for path in "$GCM_HOME" "$LAUNCHER"; do
        # The folder goes into the launcher as a Python string, and the launcher's path
        # into the desktop entry's Exec, quoted: each of these would need escaping in one
        # or the other.
        case $path in
            *[\"\\\`\$%]* | *$'\n'*)
                die "cannot install under $path: its name holds one of \" \\ \` \$ % or a new line" ;;
        esac
    done
}

# Refuses to replace a file this script did not write.
check_ours() {
    if [[ -e $1 ]] && ! grep -qF "$MARKER" "$1"; then
        die "$1 was not written by this script. Move it away, and run this again."
    fi
}

# The packages a version's .deb names with the options given, read from its Makefile, so
# that a version needing another one gets it. Alternatives are one quoted word there,
# `'a|b'`, read without the quotes (#273).
deb_packages() {
    awk -v option="^($2)\$" -v quote="'" '
        /^deb:/ { deb = 1; next }
        deb && $0 != "" && substr($0, 1, 1) != "\t" { exit }
        deb { for (i = 1; i < NF; i++) if ($i ~ option) { name = $(i + 1); gsub(quote, "", name); print name } }
    ' "$1/Makefile"
}

# What the .deb depends on and recommends, and git, for the updates.
version_packages() {
    deb_packages "$1" '-d|--deb-recommends'
    say git
}

# What it suggests: GCM's optional programs, each used by one kind of host or one feature.
optional_packages() {
    deb_packages "$1" '--deb-suggests'
}

# Those of the packages named that are not installed. Alternatives, `a|b`, are installed
# while any one of them is, and are named as the first, the one to install.
missing_packages() {
    local package alternative alternatives status
    for package in "$@"; do
        IFS='|' read -ra alternatives <<<"$package"
        for alternative in "${alternatives[@]}"; do
            status=$(dpkg-query -W -f='${Status}' "$alternative" 2>/dev/null) || status=
            [[ $status == *" installed" ]] && continue 2
        done
        say "${package%%|*}"
    done
}

# Asks whether to install GCM's optional programs, on the terminal: piped, the script's
# input is the script. With no terminal to ask on, the answer is no.
want_optional() {
    local answer
    if ! (: </dev/tty) 2>/dev/null; then
        say "Left out GCM's optional programs, with no terminal to ask on: $*"
        return 1
    fi
    printf '%s\n  %s\n%s' "GCM can also use these optional programs, which are not installed:" \
        "$*" "Have apt install them too? [y/N] " >/dev/tty
    read -r answer </dev/tty || answer=
    [[ $answer == [Yy] || $answer == [Yy][Ee][Ss] ]] && return 0
    say "Left out GCM's optional programs."
    return 1
}

# Has apt install those of the packages named that are missing, and, if the person running
# this wants them, those missing of the ones after a --: GCM's optional programs. Those
# have an apt-get install of their own, so that apt failing on one stops nothing else.
install_packages() {
    local required=() optional=() missing offered wanted=() sudo=()
    while (($#)) && [[ $1 != -- ]]; do
        required+=("$1")
        shift
    done
    (($# == 0)) || shift
    optional=("$@")
    if ! command -v apt-get >/dev/null || ! command -v dpkg-query >/dev/null; then
        say "There is no apt here to install what GCM needs. In Debian's names: ${required[*]%%|*}"
        ((${#optional[@]} == 0)) || say "Its optional programs, if you want them: ${optional[*]%%|*}"
        return 0
    fi
    mapfile -t missing < <(missing_packages "${required[@]}")
    mapfile -t offered < <(missing_packages "${optional[@]}")
    ((${#missing[@]} + ${#offered[@]})) || return 0
    if ((EUID != 0)); then
        if ! command -v sudo >/dev/null; then
            ((${#offered[@]} == 0)) ||
                say "sudo was not found. For GCM's optional programs, as root, run: apt-get install ${offered[*]}"
            ((${#missing[@]} == 0)) || die "sudo was not found. As root, run: apt-get install ${missing[*]}"
            return 0
        fi
        sudo=(sudo)
    fi
    if ((${#offered[@]})) && want_optional "${offered[@]}"; then
        wanted=("${offered[@]}")
    fi
    ((${#missing[@]} + ${#wanted[@]})) || return 0
    ((${#missing[@]} == 0)) || say "apt will install what GCM needs: ${missing[*]}"
    ((${#wanted[@]} == 0)) || say "apt will install GCM's optional programs: ${wanted[*]}"
    "${sudo[@]}" apt-get update
    ((${#missing[@]} == 0)) || "${sudo[@]}" apt-get install -y "${missing[@]}"
    if ((${#wanted[@]})) && ! "${sudo[@]}" apt-get install -y "${wanted[@]}"; then
        say "apt could not install GCM's optional programs, so GCM is installed without them."
    fi
}

need_git() {
    command -v git >/dev/null && return 0
    install_packages git
    command -v git >/dev/null || die "git is needed, and was not found"
}

# Only one run at a time: two would add the same worktree.
lock_install() {
    mkdir -p "$GCM_HOME"
    command -v flock >/dev/null || return 0
    exec 9>"$GCM_HOME/install.lock"
    flock --nonblock 9 || die "another run of install.sh is installing GCM"
}

fetch_repo() {
    # A repository that asks for a password fails instead: none of GCM's does.
    export GIT_TERMINAL_PROMPT=0
    if [[ ! -d $REPO ]]; then
        say "Cloning $REPO_URL"
        # Cloned under a name of its own and then moved, so that the clone's name never
        # names one cut short.
        rm -rf "$REPO.new"
        git clone --quiet --bare "$REPO_URL" "$REPO.new"
        # A bare clone keeps no remote branches unless told to, and main is read there.
        git --git-dir="$REPO.new" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
        mv "$REPO.new" "$REPO"
    else
        git --git-dir="$REPO" remote set-url origin "$REPO_URL"
    fi
    # --force follows a tag moved upstream rather than failing on it, as a plain fetch
    # of a moved tag does.
    git --git-dir="$REPO" fetch --quiet --force --tags origin
}

# The newest vX.Y.Z tag, compared as numbers: what GCM's update check reads too (#295).
newest_release() {
    git --git-dir="$REPO" tag --list --sort=-version:refname 'v*' |
        awk '/^v[0-9]+\.[0-9]+\.[0-9]+$/ && !found { print; found = 1 }'
}

# Sets VERSION_NAME and VERSION_COMMIT for release, main or a vX.Y.Z.
resolve() {
    local tag=$1
    if [[ $tag == main ]]; then
        VERSION_COMMIT=$(git --git-dir="$REPO" rev-parse --verify --quiet 'refs/remotes/origin/main^{commit}') ||
            die "$REPO_URL has no main branch"
        VERSION_NAME=main-${VERSION_COMMIT:0:12}
        return 0
    fi
    if [[ $tag == release ]]; then
        tag=$(newest_release)
        [[ -n $tag ]] || die "$REPO_URL has no release yet. Its main branch installs with: install.sh main"
    fi
    VERSION_COMMIT=$(git --git-dir="$REPO" rev-parse --verify --quiet "refs/tags/$tag^{commit}") ||
        die "$REPO_URL has no release $tag"
    VERSION_NAME=$tag
}

add_version() {
    local dir=$VERSIONS/$VERSION_NAME new=$VERSIONS/.new head
    if [[ -d $dir ]]; then
        head=$(GIT_CEILING_DIRECTORIES=$VERSIONS git -C "$dir" rev-parse HEAD 2>/dev/null) || head=
        [[ $head == "$VERSION_COMMIT" ]] ||
            die "$dir is not $VERSION_NAME as $REPO_URL has it now. Run install.sh --uninstall, then install again."
        return 0
    fi
    say "Adding $VERSION_NAME"
    rm -rf "$new"
    git --git-dir="$REPO" worktree prune
    mkdir -p "$VERSIONS"
    # Added under a name of its own and then moved, as the clone is.
    git --git-dir="$REPO" worktree add --quiet --detach "$new" "$VERSION_COMMIT"
    git --git-dir="$REPO" worktree move "$new" "$dir"
}

# The name of the version a link names, if it names one.
link_name() {
    local target
    target=$(readlink "$GCM_HOME/$1" 2>/dev/null) || return 0
    say "${target##*/}"
}

# Replaces a link in one step, so that a launcher starting meanwhile never finds none.
relink() {
    ln -sfn "$1" "$2.new"
    mv -Tf "$2.new" "$2"
}

# Moves `current` to the version, and `previous` to the one it named. Sets REPLACED to
# that one, and CHANGED unless the version was current already.
use_version() {
    REPLACED=$(link_name current)
    CHANGED=
    [[ $REPLACED != "$VERSION_NAME" ]] || return 0
    CHANGED=1
    relink "versions/$VERSION_NAME" "$GCM_HOME/current"
    [[ -z $REPLACED ]] || relink "versions/$REPLACED" "$GCM_HOME/previous"
}

# Whether a GCM started from the version still runs: the launcher holds a shared lock on
# its version for as long as GCM does. Without flock, every version counts as in use.
in_use() {
    command -v flock >/dev/null || return 0
    ! flock --nonblock --exclusive "$1" true
}

# Removes every version but the current one and the one before it, unless in use.
prune() {
    local dir name current previous
    current=$(link_name current)
    previous=$(link_name previous)
    for dir in "$VERSIONS"/*; do
        [[ -d $dir && ! -L $dir ]] || continue
        name=${dir##*/}
        [[ $name != "$current" && $name != "$previous" ]] || continue
        if in_use "$dir"; then
            say "Kept $name, which a GCM still running was started from."
            continue
        fi
        git --git-dir="$REPO" worktree remove --force "$dir"
        say "Removed $name."
    done
}

write_launcher() {
    mkdir -p "${LAUNCHER%/*}"
    cat >"$LAUNCHER.new" <<EOF
#!/usr/bin/python3
# $MARKER (#294), which writes it again at each update.
"""Starts the version of GCM that current names, resolved once, as GCM starts.

An update moves current and never changes a version's files, so a running GCM keeps the
ones it started with. The lock taken here is shared, held while GCM runs and not
inherited by its tabs, and an update removes no version a lock is held on.
"""

import fcntl
import os
import sys

CURRENT = "$GCM_HOME/current"

version = os.path.realpath(CURRENT)
if not os.path.isdir(os.path.join(version, "src", "gnome_connection_manager")):
    sys.exit(f"{CURRENT} names no version of GCM. Run GCM's install.sh again.")
lock = os.open(version, os.O_RDONLY)
fcntl.flock(lock, fcntl.LOCK_SH)
# A GCM started from a console of another inherits these from it, and would take that
# GCM's files for its own.
for name in ("GCM_DATA_DIR", "GCM_GLADE_DIR", "GCM_SCRIPTS_DIR"):
    os.environ.pop(name, None)
sys.path.insert(0, os.path.join(version, "src"))

from gnome_connection_manager.__main__ import main  # noqa: E402

sys.exit(main())
EOF
    chmod 755 "$LAUNCHER.new"
    mv -f "$LAUNCHER.new" "$LAUNCHER"
}

# The version's own desktop entry, with the launcher to run and the icon in `current`.
write_desktop_entry() {
    local exec=$LAUNCHER
    # Quoted only where the spec reserves a character in it: GLib launches a quoted Exec
    # correctly, but its get_executable gives the text up to the first space, quote and
    # all.
    case $exec in
        *[[:space:]\'\>\<\~\|\&\;\*\?\#\(\)]*) exec="\"$exec\"" ;;
    esac
    mkdir -p "${DESKTOP_ENTRY%/*}"
    COMMENT="# $MARKER (#294), which writes it again at each update." \
        EXEC="Exec=$exec" ICON="Icon=$GCM_HOME/current/data/icon.png" awk '
            NR == 1 { print ENVIRON["COMMENT"] }
            /^Exec=/ { print ENVIRON["EXEC"]; next }
            /^Icon=/ { print ENVIRON["ICON"]; next }
            { print }
        ' "$GCM_HOME/current/gnome-connection-manager.desktop" >"$DESKTOP_ENTRY.new"
    mv -f "$DESKTOP_ENTRY.new" "$DESKTOP_ENTRY"
}

report() {
    if [[ -z $CHANGED ]]; then
        say "GCM $VERSION_NAME is installed already."
    elif [[ -n $REPLACED ]]; then
        say "GCM $VERSION_NAME is installed, in place of $REPLACED."
        if [[ -d $VERSIONS/$REPLACED ]] && in_use "$VERSIONS/$REPLACED"; then
            say "A GCM already running goes on with $REPLACED until it is closed."
        fi
    else
        say "GCM $VERSION_NAME is installed."
    fi
    say "Start it from your desktop's menu, or with: gnome-connection-manager"
    case ":$PATH:" in
        *":${LAUNCHER%/*}:"*) ;;
        *) say "${LAUNCHER%/*} is not on your PATH yet. Ubuntu adds it once you log in again; until then, run $LAUNCHER." ;;
    esac
}

remove_ours() {
    [[ -e $1 ]] || return 0
    if grep -qF "$MARKER" "$1"; then
        rm -f "$1"
        say "Removed $1."
    else
        say "Left $1, which this script did not write."
    fi
}

uninstall() {
    local dir running=()
    if [[ ! -e $LAUNCHER && ! -e $DESKTOP_ENTRY && ! -e $GCM_HOME ]]; then
        say "GCM is not installed here, so there is nothing to remove."
        return 0
    fi
    for dir in "$VERSIONS"/*; do
        [[ -d $dir && ! -L $dir ]] || continue
        if in_use "$dir"; then
            running+=("${dir##*/}")
        fi
    done
    ((${#running[@]} == 0)) || die "GCM is running, started from ${running[*]}. Close it, and run this again."
    remove_ours "$LAUNCHER"
    remove_ours "$DESKTOP_ENTRY"
    if [[ -d $GCM_HOME ]]; then
        rm -rf "$GCM_HOME"
        say "Removed $GCM_HOME."
    fi
    say "Kept GCM's configuration, with your hosts, and the packages apt installed."
}

main() {
    local arg spec='' remove='' channel packages optional
    for arg in "$@"; do
        case $arg in
            --uninstall) remove=1 ;;
            release | main) spec=$arg ;;
            -h | --help)
                usage
                return 0 ;;
            *)
                [[ $arg =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "unknown argument: $arg (see --help)"
                spec=$arg ;;
        esac
    done
    set_paths
    # Not wherever it was run from, which could be another repository, or a version this
    # run removes.
    cd /
    if [[ -n $remove ]]; then
        uninstall
        return 0
    fi
    check_ours "$LAUNCHER"
    check_ours "$DESKTOP_ENTRY"
    need_git
    lock_install
    fetch_repo
    channel=$spec
    if [[ -z $channel ]]; then
        channel=$(cat "$GCM_HOME/channel" 2>/dev/null) || channel=
        [[ $channel == main ]] || channel=release
    fi
    resolve "$channel"
    add_version
    mapfile -t packages < <(version_packages "$VERSIONS/$VERSION_NAME")
    ((${#packages[@]} > 1)) || die "found no packages in $VERSIONS/$VERSION_NAME/Makefile"
    mapfile -t optional < <(optional_packages "$VERSIONS/$VERSION_NAME")
    install_packages "${packages[@]}" -- "${optional[@]}"
    use_version
    write_launcher
    write_desktop_entry
    if [[ $spec == release || $spec == main ]]; then
        say "$spec" >"$GCM_HOME/channel"
    fi
    prune
    report
}

# In braces, so that a download cut short within this line runs nothing either: cut after
# `main`, it would run with none of its arguments.
{ main "$@"; }
