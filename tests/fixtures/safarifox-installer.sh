#!/usr/bin/env bash
# Test double preserving upstream browser detection and profile-install contracts.
set -Eeuo pipefail
# --- Detect user environment ---
MY_HOME=/not-the-test-home
# --- Firefox directories ---
get_profiles() {
    find "$1" -mindepth 1 -maxdepth 1 -type d -name '*.default*'
}
install_to_profile() {
    mkdir -p "$1/chrome"
    echo 'SafariFox test CSS' > "$1/chrome/userChrome.css"
}
main() {
    local root found profile installed=0
    # Like upstream, this detection can disagree with snap list firefox / flatpak info.
    if snap list 2>/dev/null | grep -q firefox; then
        root="$MY_HOME/snap/firefox/common/.mozilla/firefox"
    elif flatpak list --app 2>/dev/null | grep -q org.mozilla.firefox; then
        root="$MY_HOME/.var/app/org.mozilla.firefox/.mozilla/firefox"
    else
        root="$MY_HOME/.mozilla/firefox"
    fi
    [[ -d $root ]] || return 1
    found=$(get_profiles "$root") || return 1
    [[ -n $found ]] || return 1
    while IFS= read -r profile; do
        install_to_profile "$profile"
        ((installed++))
    done <<< "$found"
    (( installed > 0 ))
}
# --- Run main ---
main
