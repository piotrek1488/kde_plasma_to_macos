#!/usr/bin/env bash
# Test doubles only: never execute privileged, network, or desktop commands.
set -Eeuo pipefail
name=${0##*/}
printf '%s\t%s\n' "$name" "$*" >> "$TEST_ROOT/commands.log"
create_firefox_profile() {
    [[ ${TEST_PROFILE_CREATE_FAIL:-0} == 0 ]] || return 44
    local root
    case "$1" in
        snap) root="$HOME/snap/firefox/common/.mozilla/firefox" ;;
        flatpak) root="$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox" ;;
        *) root="$HOME/${TEST_NATIVE_PROFILE_ROOT:-.mozilla/firefox}" ;;
    esac
    mkdir -p "$root/test.default-release"
    printf '[Profile0]\nName=default-release\nIsRelative=1\nPath=test.default-release\nDefault=1\n' > "$root/profiles.ini"
}
case "$name" in
    plasmashell) echo 'plasmashell 6.6.4' ;;
    dpkg-query) printf 'base-package\t1.0\tinstalled\n' ;;
    apt-mark) if [[ ${1:-} == showmanual ]]; then echo base-package; fi ;;
    dpkg) echo "${TEST_ARCH:-amd64}" ;;
    firefox)
        if [[ $* == *-CreateProfile* ]]; then create_firefox_profile native
        else [[ ${TEST_FIREFOX:-native} == native ]]; fi
        ;;
    snap)
        if [[ $* == *-CreateProfile* ]]; then create_firefox_profile snap
        elif [[ $* == list ]]; then
            echo 'Name Version Rev Tracking Publisher Notes'
            if [[ ${TEST_FIREFOX:-native} == snap && ${TEST_BROKEN_SAFARIFOX_DETECTION:-0} == 0 ]]; then echo 'firefox 1 1 latest/stable mozilla -'; fi
        else
            [[ ${TEST_FIREFOX:-native} == snap ]]
        fi
        ;;
    flatpak)
        if [[ $* == *-CreateProfile* ]]; then create_firefox_profile flatpak
        elif [[ ${2:-} == info && ${3:-} == org.mozilla.firefox ]]; then
            [[ ${TEST_FIREFOX:-native} == "flatpak-${1#--}" ]]
        fi
        ;;
    sudo)
        case "${1:-}" in
            test) exit 1 ;;
            apt-get)
                if [[ $* == 'apt-get -s remove '* && ${TEST_APT_REMOVE_ORIGINAL:-0} == 1 ]]; then
                    echo 'Remv existing [1]'
                fi
                if [[ $* == 'apt-get install -y --no-remove firefox' && ${TEST_FIREFOX_INSTALL_FAIL:-0} == 1 ]]; then
                    exit 42
                fi
                ;;
            python3)
                # Create an empty system journal; never read or change host system paths.
                if [[ ${5:-} == init ]]; then /usr/bin/python3 "${@:2}"; fi
                ;;
            add-apt-repository|mkdir|rsync|cp|cmake|snap|apt-mark|systemctl) ;;
            tee) cat > "$TEST_ROOT/sddm-theme.conf" ;;
            *) echo "Unexpected sudo command: $*" >&2; exit 99 ;;
        esac
        ;;
    git)
        if [[ ${1:-} == clone || ${1:-} == init ]]; then
            dest=${!#}
            mkdir -p "$dest/.git"
            printf '#!/bin/sh\nexit 0\n' > "$dest/install.sh"
            echo 'Upstream Punchi Dock attribution' > "$dest/NOTICE"
            if [[ $* == *linuxscoop/safarifox-theme* ]]; then
                cp "$TEST_ROOT/project with spaces/tests/fixtures/safarifox-installer.sh" "$dest/install.sh"
            fi
        fi
        ;;
    curl)
        while (( $# )); do
            if [[ $1 == -o ]]; then
                shift
                printf '#!/bin/sh\nexit 0\n' > "$1"
            fi
            shift
        done
        ;;
    sha256sum)
        cat >/dev/null
        [[ ${TEST_BAD_CHECKSUM:-0} == 0 ]]
        ;;
    systemctl)
        if [[ $* == *is-active* && ${TEST_FALLBACK:-0} == 1 ]]; then exit 1; fi
        if [[ $* == *start* && ${TEST_FAIL_START:-0} == 1 ]]; then exit 1; fi
        ;;
    rsync)
        if [[ ${TEST_FAIL_CONFIG:-0} == 1 && $* == *--backup-dir=*/kde-config* ]]; then exit 9; fi
        exec /usr/bin/rsync "$@"
        ;;
    dconf)
        if [[ ${1:-} == dump ]]; then printf '[test]\nvalue=true\n'; fi
        if [[ ${1:-} == load ]]; then cat >/dev/null; fi
        ;;
    cmake)
        if [[ $* == *punchi-build* && ${TEST_PUNCHI_BUILD_FAIL:-0} == 1 ]]; then exit 43; fi
        if [[ -n ${DESTDIR:-} ]]; then
            if [[ $* == *punchi-build* ]]; then
                package="$DESTDIR/usr/share/plasma/plasmoids/org.kde.plasma.punchi-dock-remastered"
                mkdir -p "$package/contents/ui/org/punchi/dock" "$DESTDIR/usr/share/locale/es/LC_MESSAGES"
                echo '{"KPlugin":{"Id":"org.kde.plasma.punchi-dock-remastered"}}' > "$package/metadata.json"
                echo 'GPL-3.0-or-later' > "$package/LICENSE"
                if [[ ${TEST_PUNCHI_MISSING_MODULE:-0} == 0 ]]; then
                    touch "$package/contents/ui/org/punchi/dock/libpunchidockintegrationplugin.so"
                    touch "$package/contents/ui/org/punchi/dock/libpunchidockintegration.so"
                    echo 'module org.punchi.dock' > "$package/contents/ui/org/punchi/dock/qmldir"
                fi
                echo 'test translation' > "$DESTDIR/usr/share/locale/es/LC_MESSAGES/plasma_applet_org.kde.plasma.punchi-dock-remastered.mo"
            else
                mkdir -p "$DESTDIR/usr/share/appgrid"
                echo 'test AppGrid payload' > "$DESTDIR/usr/share/appgrid/test"
            fi
        fi
        ;;
    gsettings|kstart|kquitapp6|kwriteconfig6|fc-cache|qdbus6) ;;
    *) echo "Unknown test command: $name" >&2; exit 99 ;;
esac
