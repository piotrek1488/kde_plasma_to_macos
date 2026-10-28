#!/usr/bin/env bash
# Shared rollback bookkeeping. All inventories describe the current user/system.
record_inventory() {
    local phase=$1
    rm -f "$BACKUP/inventory-$phase-complete"
    dpkg-query -W -f='${binary:Package}\t${Version}\t${db:Status-Status}\n' |
        awk -F '\t' '$3 == "installed" { print $1 "\t" $2 }' |
        LC_ALL=C sort > "$BACKUP/packages-$phase.tsv" || return 1
    apt-mark showmanual | LC_ALL=C sort > "$BACKUP/manual-$phase.txt" || return 1
    : > "$BACKUP/flatpak-$phase.txt"
    : > "$BACKUP/remotes-$phase.txt"
    if command -v flatpak >/dev/null; then
        flatpak --user list --columns=ref | LC_ALL=C sort > "$BACKUP/flatpak-$phase.txt" || return 1
        flatpak --user remotes --columns=name | LC_ALL=C sort > "$BACKUP/remotes-$phase.txt" || return 1
    fi
    : > "$BACKUP/snaps-$phase.txt"
    if command -v snap >/dev/null; then
        snap list > "$BACKUP/snap-inventory-$phase.txt" || return 1
        awk 'NR > 1 && NF > 1 {print $1}' "$BACKUP/snap-inventory-$phase.txt" |
            LC_ALL=C sort > "$BACKUP/snaps-$phase.txt" || return 1
    fi
    if grep -qx firefox "$BACKUP/snaps-$phase.txt"; then
        printf 'installed\n' > "$BACKUP/firefox-snap-$phase.txt"
    else
        : > "$BACKUP/firefox-snap-$phase.txt"
    fi
    touch "$BACKUP/inventory-$phase-complete"
}

capture_user_path() {
    python3 "$STATE_HELPER" "$BACKUP/user-state" "$HOME" path "$1"
}

capture_system_path() {
    sudo python3 "$STATE_HELPER" "$BACKUP/system-state" "$HOME" path "$1"
}

start_rollback_record() {
    python3 "$STATE_HELPER" "$BACKUP/user-state" "$HOME" init user
    sudo python3 "$STATE_HELPER" "$BACKUP/system-state" "$HOME" init system
    record_inventory before
    # Repository and display-manager files can be changed by Ubuntu package scripts.
    capture_system_path /etc/apt/sources.list
    capture_system_path /etc/apt/sources.list.d
    capture_system_path /etc/X11/default-display-manager
    capture_system_path /etc/systemd/system/display-manager.service
    printf '1\n' > "$BACKUP/rollback-version"
}

installation_cleanup() {
    local result=$?
    trap - EXIT
    if [[ ${PLASMA_STOPPED:-0} == 1 ]]; then
        restart_plasma || echo 'Could not restart Plasma automatically.' >&2
    fi
    record_inventory after || echo 'Could not finish the package inventory; review this backup before uninstalling.' >&2
    rm -rf -- "$WORK"
    return "$result"
}
