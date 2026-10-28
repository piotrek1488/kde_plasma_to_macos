#!/usr/bin/env bash
# Restore the state saved by install.sh. Preview by default; use --apply to restore.
set -Eeuo pipefail
# shellcheck source-path=SCRIPTDIR
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=install.sh
source "$SCRIPT_DIR/install.sh"
STATE_HELPER="$SCRIPT_DIR/scripts/file-state.py"
export LC_ALL=C

stop_plasma_for_restore() {
    # Stop Plasma while restoring its files, and always try to restart it on failure.
    PLASMA_STOPPED=0
    trap 'if [[ $PLASMA_STOPPED == 1 ]]; then restart_plasma; fi' EXIT
    if [[ ${XDG_CURRENT_DESKTOP:-} == *KDE* ]]; then
        if systemctl --user is-active --quiet plasma-plasmashell.service; then
            systemctl --user stop plasma-plasmashell.service
        else
            kquitapp6 plasmashell
        fi
        PLASMA_STOPPED=1
    fi
}

resume_plasma_after_restore() {
    if [[ $PLASMA_STOPPED == 1 ]]; then restart_plasma; PLASMA_STOPPED=0; fi
    trap - EXIT
}

legacy_restore() {
    local label dest scope
    echo 'Legacy backup: only overwritten files and saved dconf values can be restored.'
    echo 'New files, packages, Firefox profiles, and earlier Flatpak settings were not recorded.'
    local mappings=(
        'plasma-theme|.local/share' 'gtk-theme|.themes' 'kvantum|.config/Kvantum'
        'icons|.local/share/icons' 'cursors|.local/share/icons' 'fonts|.local/share/fonts'
        'plasmoids|.local/share/plasma/plasmoids' 'kwin|.local/share/kwin'
        'plasma-wallpapers|.local/share/plasma/wallpapers' 'cava|.config'
        'fastfetch|.local/share/fastfetch' 'zsh-konsole|.' 'kde-config|.config'
        'system-wallpapers|/usr/share/wallpapers' 'sddm-themes|/usr/share/sddm/themes'
    )
    for mapping in "${mappings[@]}"; do
        label=${mapping%%|*}; dest=${mapping#*|}
        [[ -d $BACKUP/$label ]] || continue
        echo "Restore $label -> $dest"
    done
    [[ -f $BACKUP/dconf.ini ]] && echo 'Reload saved dconf values (without deleting unknown keys).'
    if [[ $APPLY == 0 ]] || ! confirm 'Restore the available legacy backup files?'; then return 0; fi
    prepare_recovery
    python3 "$STATE_HELPER" "$RECOVERY/user-state" "$HOME" init user
    sudo python3 "$STATE_HELPER" "$RECOVERY/system-state" "$HOME" init system
    stop_plasma_for_restore
    for mapping in "${mappings[@]}"; do
        label=${mapping%%|*}; dest=${mapping#*|}
        [[ -d $BACKUP/$label ]] || continue
        scope=user
        if [[ $dest == /* ]]; then scope=system; else dest="$HOME/$dest"; fi
        if [[ $scope == system ]]; then
            sudo python3 "$STATE_HELPER" "$RECOVERY/system-state" "$HOME" copy "$BACKUP/$label" "$dest"
            sudo rsync -a "$BACKUP/$label/" "$dest/"
        else
            python3 "$STATE_HELPER" "$RECOVERY/user-state" "$HOME" copy "$BACKUP/$label" "$dest"
            rsync -a "$BACKUP/$label/" "$dest/"
        fi
    done
    if [[ -f $BACKUP/zz-macos-theme.conf ]]; then
        sudo python3 "$STATE_HELPER" "$RECOVERY/system-state" "$HOME" path /etc/sddm.conf.d/zz-macos-theme.conf
        sudo cp -a "$BACKUP/zz-macos-theme.conf" /etc/sddm.conf.d/zz-macos-theme.conf
    fi
    if [[ -f $BACKUP/dconf.ini ]]; then
        dconf dump / > "$RECOVERY/dconf.ini"
        dconf load / < "$BACKUP/dconf.ini"
    fi
    resume_plasma_after_restore
    touch "$BACKUP/restored"
    echo "Available legacy settings restored. Current files were saved in: $RECOVERY"
}

prepare_recovery() {
    RECOVERY="$HOME/.local/state/kde-plasma-to-macos/recovery/$(date +%Y%m%d-%H%M%S)-$$"
    mkdir -p "$RECOVERY"
    chmod 700 "$RECOVERY"
    echo "Pre-uninstall recovery copy: $RECOVERY"
}

main_uninstall() {
    APPLY=0
    BACKUP=''
    while (( $# )); do
        case "$1" in
            --help)
                echo 'Usage: bash uninstall.sh [--backup DIRECTORY] [--apply]'
                echo 'Preview the latest unrestored backup by default. --apply asks for Y/N confirmation.'
                echo 'Older backups support only partial restoration of overwritten files.'
                return 0 ;;
            --apply) APPLY=1; shift ;;
            --backup)
                [[ $# -ge 2 ]] || { echo 'Missing backup directory.' >&2; return 1; }
                BACKUP=$2; shift 2 ;;
            *) echo "Unknown argument: $1" >&2; return 1 ;;
        esac
    done
    (( EUID != 0 )) || { echo 'Run without sudo, as the user who installed the themes.' >&2; return 1; }
    if [[ -z $BACKUP ]]; then
        BACKUP=$(python3 - "$HOME/.local/state/kde-plasma-to-macos/backups" <<'PY'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
candidates = sorted(p for p in root.glob('*') if p.is_dir() and not (p / 'restored').exists())
if candidates:
    print(candidates[-1])
PY
)
    fi
    [[ -d $BACKUP ]] || { echo 'No backup found. Specify --backup DIRECTORY.' >&2; return 1; }
    BACKUP=$(cd -- "$BACKUP" && pwd)
    [[ ! -f $BACKUP/restored ]] || { echo 'This backup has already been restored.' >&2; return 1; }
    echo "Selected backup: $BACKUP"
    if [[ ! -f $BACKUP/rollback-version ]]; then legacy_restore; return; fi
    [[ $(cat "$BACKUP/rollback-version") == 1 ]] || { echo 'Unsupported backup version.' >&2; return 1; }
    for required in packages-before.tsv packages-after.tsv manual-before.txt manual-after.txt \
        flatpak-before.txt flatpak-after.txt remotes-before.txt remotes-after.txt \
        firefox-snap-before.txt firefox-snap-after.txt snaps-before.txt snaps-after.txt \
        inventory-before-complete inventory-after-complete; do
        [[ -f $BACKUP/$required ]] || { echo "Incomplete inventory: $required. No changes made." >&2; return 1; }
    done
    # Both commands verify paths and snapshot availability before anything is changed.
    python3 "$STATE_HELPER" "$BACKUP/user-state" "$HOME" restore
    sudo python3 "$STATE_HELPER" "$BACKUP/system-state" "$HOME" restore
    mapfile -t NEW_PACKAGES < <(comm -13 <(cut -f1 "$BACKUP/packages-before.tsv") <(cut -f1 "$BACKUP/packages-after.tsv"))
    mapfile -t NEW_SNAPS < <(comm -13 "$BACKUP/snaps-before.txt" "$BACKUP/snaps-after.txt")
    mapfile -t NEW_REFS < <(comm -13 "$BACKUP/flatpak-before.txt" "$BACKUP/flatpak-after.txt")
    mapfile -t NEW_REMOTES < <(comm -13 "$BACKUP/remotes-before.txt" "$BACKUP/remotes-after.txt")
    mapfile -t NEW_MANUAL < <(comm -13 "$BACKUP/manual-before.txt" "$BACKUP/manual-after.txt" |
        comm -12 - <(cut -f1 "$BACKUP/packages-before.tsv"))
    echo "APT packages added by installation: ${NEW_PACKAGES[*]:-(none)}"
    echo "Snap packages added by installation: ${NEW_SNAPS[*]:-(none)}"
    echo "Flatpak refs added by installation: ${NEW_REFS[*]:-(none)}"
    echo "Flatpak remotes added by installation: ${NEW_REMOTES[*]:-(none)}"
    echo 'Existing package upgrades are not downgraded; see packages-before.tsv and packages-after.tsv.'
    if [[ $APPLY == 0 ]]; then echo 'Preview only. Use --apply to restore.'; return 0; fi
    for package in "${NEW_PACKAGES[@]}"; do
        if [[ ${package%%:*} == sddm && ${XDG_SESSION_TYPE:-} != tty && -n ${XDG_CURRENT_DESKTOP:-} ]] &&
            systemctl is-active --quiet sddm.service; then
            echo 'Removing the running SDDM would terminate this desktop session.' >&2
            echo 'Run from a text console instead: dbus-run-session bash uninstall.sh --apply' >&2
            return 1
        fi
    done
    if ! confirm 'Restore this backup and remove the packages added by installation?'; then return 0; fi
    prepare_recovery
    # Package removal must never take an originally installed package with it.
    if (( ${#NEW_PACKAGES[@]} )); then
        # The unprivileged recovery directory intentionally owns the redirected plan.
        # shellcheck disable=SC2024
        sudo apt-get -s remove --no-auto-remove -- "${NEW_PACKAGES[@]}" > "$RECOVERY/apt-removal-plan.txt"
        python3 - "$BACKUP/packages-before.tsv" "$RECOVERY/apt-removal-plan.txt" "${NEW_PACKAGES[@]}" <<'PY'
import pathlib, sys
original = {line.split('\t')[0].split(':')[0] for line in pathlib.Path(sys.argv[1]).read_text().splitlines()}
removed = {line.split()[1].split(':')[0] for line in pathlib.Path(sys.argv[2]).read_text().splitlines() if line.startswith('Remv ')}
allowed = {name.split(':')[0] for name in sys.argv[3:]}
if original & removed or removed - allowed:
    sys.exit('APT would remove originally installed or later-added packages. Restoration stopped before changes.')
PY
    fi
    python3 "$STATE_HELPER" "$BACKUP/user-state" "$HOME" save-current "$RECOVERY/user-state"
    sudo python3 "$STATE_HELPER" "$BACKUP/system-state" "$HOME" save-current "$RECOVERY/system-state"
    # Keep Flatpak available until its newly installed refs have been removed.
    for ref in "${NEW_REFS[@]}"; do
        if flatpak --user info "$ref" >/dev/null 2>&1; then
            flatpak --user uninstall -y --noninteractive --no-related -- "$ref"
        fi
    done
    for remote in "${NEW_REMOTES[@]}"; do
        flatpak --user remote-delete "$remote" || echo "Remote $remote is still in use; it was retained." >&2
    done
    # Remove apps before their content/base snaps. Retry dependencies until no progress is made.
    pending=("${NEW_SNAPS[@]}")
    while (( ${#pending[@]} )); do
        remaining=()
        for snap_name in "${pending[@]}"; do
            snap list "$snap_name" >/dev/null 2>&1 || continue
            if ! sudo snap remove "$snap_name"; then remaining+=("$snap_name"); fi
        done
        if (( ${#remaining[@]} == ${#pending[@]} )); then
            echo "Snaps still in use were retained: ${remaining[*]}" >&2
            # Keep the Snap daemon when a retained snap still needs it.
            retained_packages=()
            for package in "${NEW_PACKAGES[@]}"; do
                [[ ${package%%:*} == snapd ]] || retained_packages+=("$package")
            done
            NEW_PACKAGES=("${retained_packages[@]}")
            break
        fi
        pending=("${remaining[@]}")
    done

    stop_plasma_for_restore
    python3 "$STATE_HELPER" "$BACKUP/user-state" "$HOME" restore --apply --recovery "$RECOVERY/user-state"
    for prefix in gnome gtk; do
        if [[ -f $BACKUP/dconf/ready && -f $BACKUP/dconf/$prefix.ini ]]; then
            mkdir -p "$RECOVERY/dconf"
            dconf dump "/org/$prefix/" > "$RECOVERY/dconf/$prefix.ini"
            dconf reset -f "/org/$prefix/"
            dconf load "/org/$prefix/" < "$BACKUP/dconf/$prefix.ini"
        fi
    done
    if (( ${#NEW_PACKAGES[@]} )); then sudo apt-get remove -y --no-auto-remove -- "${NEW_PACKAGES[@]}"; fi
    if (( ${#NEW_MANUAL[@]} )); then sudo apt-mark auto "${NEW_MANUAL[@]}"; fi
    sudo python3 "$STATE_HELPER" "$BACKUP/system-state" "$HOME" restore --apply --recovery "$RECOVERY/system-state"
    sudo systemctl daemon-reload
    if command -v fc-cache >/dev/null; then fc-cache -f; fi
    resume_plasma_after_restore
    touch "$BACKUP/restored"
    echo "Recorded files and settings restored. Pre-uninstall files are saved in: $RECOVERY"
    echo 'Log out and back in to apply the restored desktop settings.'
}

main_uninstall "$@"
