#!/usr/bin/env bash
# Ubuntu/Kubuntu 26.04 LTS, KDE Plasma 6, amd64.
# Run as a regular user in a Plasma session: bash install.sh
set -Eeuo pipefail
# shellcheck source-path=SCRIPTDIR

# Archives have different wrapper directories. Return the actual content directory.
unpack() {
    local name=$1
    mkdir -p "$WORK/$name"
    unzip -q -o "$SOURCES/$name.zip" -d "$WORK/$name" || return 1
    if [[ -d $WORK/$name/$name ]]; then
        printf '%s\n' "$WORK/$name/$name"
    else
        printf '%s\n' "$WORK/$name"
    fi
}

# Keep previous versions of files overwritten by rsync.
copy_user() {
    local src=$1 dest=$2 label=$3
    if [[ -f $BACKUP/user-state/manifest.json ]]; then
        python3 "$STATE_HELPER" "$BACKUP/user-state" "$HOME" copy "$src" "$dest"
    fi
    mkdir -p "$dest"
    rsync -a --backup --backup-dir="$BACKUP/$label" "$src/" "$dest/"
}

clone_if_missing() {
    local url=$1 dest=$2
    if [[ ! -e $dest ]]; then
        git clone --depth 1 "$url" "$dest"
    elif [[ ! -d $dest/.git ]]; then
        echo "Directory already exists and is not a Git repository: $dest" >&2
        return 1
    fi
}

# Preserve existing native, Snap, or Flatpak installations.
ensure_firefox() {
    if firefox --version >/dev/null 2>&1 ||
        snap list firefox >/dev/null 2>&1 ||
        flatpak --user info org.mozilla.firefox >/dev/null 2>&1 ||
        flatpak --system info org.mozilla.firefox >/dev/null 2>&1; then
        echo 'Firefox is already installed.'
        return 0
    fi
    # Ubuntu's Firefox APT package installs the Firefox Snap.
    echo 'Firefox was not found. Installing Firefox before SafariFox.'
    sudo apt-get install -y --no-remove firefox
}

# Create a registered profile only when the selected Firefox installation has none.
ensure_firefox_profile() {
    local -a browser roots
    local helper="$SCRIPT_DIR/scripts/firefox-profiles.py" found
    if snap list firefox >/dev/null 2>&1; then
        browser=(snap run firefox)
        roots=("$HOME/snap/firefox/common/.mozilla/firefox")
    elif flatpak --user info org.mozilla.firefox >/dev/null 2>&1; then
        browser=(flatpak --user run org.mozilla.firefox)
        roots=("$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox")
    elif flatpak --system info org.mozilla.firefox >/dev/null 2>&1; then
        browser=(flatpak --system run org.mozilla.firefox)
        roots=("$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox")
    else
        browser=(firefox)
        roots=("$HOME/.mozilla/firefox" "$HOME/.config/mozilla/firefox")
    fi
    found=$(python3 "$helper" list "${roots[@]}")
    if [[ -z $found ]]; then
        echo 'Creating the first Firefox profile before installing SafariFox.'
        timeout 60s "${browser[@]}" --headless --no-remote -CreateProfile default-release
        found=$(python3 "$helper" list "${roots[@]}")
        [[ -n $found ]] || {
            echo 'Firefox did not create a usable profile. Open and close Firefox, then resume this stage.' >&2
            return 1
        }
    fi
    # Registered custom profile paths may live outside the usual Firefox directory.
    while IFS= read -r profile; do
        capture_user_path "$profile"
    done <<< "$found"
}

install_safarifox() {
    ensure_firefox
    ensure_firefox_profile
    local profiles profile
    profiles=$(python3 "$SCRIPT_DIR/scripts/firefox-profiles.py" list \
        "$HOME/.mozilla/firefox" "$HOME/.config/mozilla/firefox" \
        "$HOME/snap/firefox/common/.mozilla/firefox" \
        "$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox" \
        "$HOME/.librewolf" "$HOME/.var/app/io.gitlab.librewolf-community/.librewolf" \
        "$HOME/.floorp" "$HOME/.var/app/one.ablaze.floorp/.floorp")
    while IFS= read -r profile; do
        [[ -z $profile ]] || capture_user_path "$profile"
    done <<< "$profiles"
    clone_if_missing https://github.com/linuxscoop/safarifox-theme.git "$SOURCES/safarifox-theme"
    # Adapt only a temporary copy; keep the downloaded repository unchanged.
    local stage="$WORK/safarifox-theme"
    mkdir -p "$stage"
    rsync -a --exclude=.git "$SOURCES/safarifox-theme/" "$stage/"
    local profile_list="$WORK/safarifox-profiles.txt"
    printf '%s\n' "$profiles" > "$profile_list"
    chmod 600 "$profile_list"
    python3 "$SCRIPT_DIR/scripts/firefox-profiles.py" prepare-installer "$stage/install.sh"
    (cd "$stage" && SAFARIFOX_PROFILE_HELPER="$SCRIPT_DIR/scripts/firefox-profiles.py" \
        SAFARIFOX_PROFILE_LIST="$profile_list" bash ./install.sh -f)
}

# Build a fixed upstream revision with this system's Qt/KDE libraries.
install_punchi_dock() {
    local revision=84c42df2462a411103b0bb53055d4a9a62a8fbb2
    local plugin=org.kde.plasma.punchi-dock-remastered
    local source_dir="$WORK/punchi-source" build_dir="$WORK/punchi-build"
    local stage="$WORK/punchi-stage" destination="$HOME/.local/share/plasma/plasmoids/$plugin"

    git init "$source_dir"
    git -C "$source_dir" remote add origin https://github.com/PunchiSoft/punchi-dock-remastered.git
    git -C "$source_dir" fetch --depth 1 origin "$revision"
    git -C "$source_dir" checkout --detach FETCH_HEAD
    cmake -S "$source_dir" -B "$build_dir" \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
        -DBUILD_TESTING=OFF -DPUNCHI_EMBED_QML_MODULE_IN_KPACKAGE=ON
    cmake --build "$build_dir" --parallel 2
    (umask 022; DESTDIR="$stage" cmake --install "$build_dir")

    local package="$stage/usr/share/plasma/plasmoids/$plugin"
    [[ -f $package/metadata.json && -f $package/LICENSE &&
        -f $package/contents/ui/org/punchi/dock/libpunchidockintegrationplugin.so &&
        -f $package/contents/ui/org/punchi/dock/libpunchidockintegration.so &&
        -f $package/contents/ui/org/punchi/dock/qmldir ]] || {
        echo 'Punchi Dock build did not produce the expected package and native module.' >&2
        return 1
    }
    cp "$source_dir/NOTICE" "$package/NOTICE"

    capture_user_path "$destination"
    capture_user_path "$HOME/.config/punchi-dock"
    capture_user_path "$HOME/.local/share/punchi-dock-remastered"
    mkdir -p "$destination"
    # Remove stale files from an older local dock without touching other widgets.
    rsync -a --delete --backup --backup-dir="$BACKUP/punchi-dock" "$package/" "$destination/"
    copy_user "$stage/usr/share/locale" "$HOME/.local/share/locale" punchi-translations
    printf 'Punchi Dock Remastered 0.9.7.84\nCommit: %s\n' "$revision" > "$BACKUP/punchi-dock-source.txt"
}

# Start Plasma using the systemd user service, with a fallback for other sessions.
restart_plasma() {
    if ! systemctl --user start plasma-plasmashell.service; then
        kstart plasmashell >/dev/null 2>&1 &
    fi
}

# An empty answer or end of input always declines the action.
confirm() {
    local answer
    while true; do
        if ! read -r -p "$1 [y/N]: " answer; then
            printf '\n'
            return 1
        fi
        case "$answer" in
            [Yy]) return 0 ;;
            [Nn]|'') return 1 ;;
            *) echo 'Please enter Y or N.' ;;
        esac
    done
}

# Request a restart or logout only after explicit confirmation.
finish_installation() {
    echo 'Save your work before choosing restart or logout.'
    if confirm 'Restart the computer now?'; then
        systemctl reboot
    elif confirm 'Log out of the current Plasma session now?'; then
        qdbus6 org.kde.Shutdown /Shutdown org.kde.Shutdown.logout
    else
        echo 'Installation complete. You can restart or log out later.'
    fi
}

main() {
    trap 'printf "Error on line %s. Installation stopped. Backup: %s\n" "$LINENO" "${BACKUP:-not created}" >&2' ERR
    if [[ ${1:-} == --help ]]; then
        echo 'Usage: bash install.sh (Ubuntu 26.04 amd64, active KDE Plasma 6 session).'
        echo 'Installs packages and themes and replaces the desktop layout; backs up overwritten configuration files.'
        echo 'Resume after a SafariFox failure: bash install.sh --resume-firefox BACKUP_DIRECTORY'
        echo 'To install KDE first: sudo apt install plasma-desktop plasma-workspace sddm'
        echo 'Then log out and select a Plasma session on the login screen.'
        exit 0
    fi
    local resume_backup=''
    if [[ $# == 2 && $1 == --resume-firefox ]]; then
        resume_backup=$2
    elif (( $# != 0 )); then
        echo 'Unknown argument; use --help.' >&2
        exit 1
    fi
    (( EUID != 0 )) || { echo 'Run without sudo; the script uses sudo when installing system packages and files.' >&2; exit 1; }
    # shellcheck source=/etc/os-release
    source /etc/os-release
    [[ $ID == ubuntu && $VERSION_ID == 26.04 ]] || {
        echo 'This script requires Ubuntu/Kubuntu 26.04 LTS.' >&2; exit 1;
    }
    [[ $(dpkg --print-architecture) == amd64 ]] || {
        echo 'The Darkly package used by this script supports amd64 only.' >&2; exit 1;
    }
    if ! command -v plasmashell >/dev/null || [[ $(plasmashell --version) != *' 6.'* ]] ||
        [[ ${XDG_CURRENT_DESKTOP:-} != *KDE* || -z ${DBUS_SESSION_BUS_ADDRESS:-} ]]; then
        echo 'Run from a terminal in a KDE Plasma 6 session. See: bash install.sh --help' >&2
        exit 1
    fi

    SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    SOURCES="$SCRIPT_DIR/sources"
    STATE_HELPER="$SCRIPT_DIR/scripts/file-state.py"
    # shellcheck source=scripts/state.sh
    source "$SCRIPT_DIR/scripts/state.sh"
    WORK=$(mktemp -d)
    trap 'rm -rf -- "$WORK"' EXIT
    command -v python3 >/dev/null || { echo 'Install python3 before running this installer.' >&2; exit 1; }
    if [[ -n $resume_backup ]]; then
        BACKUP=$(cd -- "$resume_backup" && pwd)
        local backup_root="$HOME/.local/state/kde-plasma-to-macos/backups"
        [[ $(dirname -- "$BACKUP") == "$backup_root" && ! -f $BACKUP/installation-complete &&
            ! -f $BACKUP/restored && -f $BACKUP/punchi-dock-source.txt &&
            -f $BACKUP/inventory-before-complete && -f $BACKUP/inventory-after-complete &&
            -f $BACKUP/rollback-version && $(cat "$BACKUP/rollback-version") == 1 ]] || {
            echo 'Resume requires an unrestored failed-install backup that reached SafariFox.' >&2
            exit 1
        }
        python3 "$STATE_HELPER" "$BACKUP/user-state" "$HOME" restore
        sudo python3 "$STATE_HELPER" "$BACKUP/system-state" "$HOME" restore
        record_inventory resume
        local inventory extension
        for inventory in packages manual flatpak remotes snaps; do
            extension=txt
            [[ $inventory != packages ]] || extension=tsv
            cmp -s "$BACKUP/$inventory-after.$extension" "$BACKUP/$inventory-resume.$extension" || {
                echo 'Installed packages or Flatpak/Snap state changed since this backup; refusing an unsafe resume.' >&2
                exit 1
            }
        done
        echo "Resuming at Firefox/SafariFox using the original backup: $BACKUP"
    else
        BACKUP="$HOME/.local/state/kde-plasma-to-macos/backups/$(date +%Y%m%d-%H%M%S)-$$"
        mkdir -p "$BACKUP"
        chmod 700 "$BACKUP"
        echo "Backups of overwritten files: $BACKUP"
        start_rollback_record
    fi
    PLASMA_STOPPED=0
    trap installation_cleanup EXIT

    if [[ -z $resume_backup ]]; then
        # Use APT instead of pacman/yay/paru. Universe includes Kvantum and Fastfetch.
        sudo apt-get update
        sudo apt-get install -y --no-remove software-properties-common
        sudo add-apt-repository -y universe
        sudo apt-get update
        sudo apt-get install -y --no-remove \
            ca-certificates curl wget rsync git sassc kate unzip zip fontconfig \
            kcalc gwenview elisa plasma-discover systemsettings \
            qt6-tools-dev-tools qt5-style-kvantum qt6-style-kvantum \
            gnome-terminal nautilus nautilus-share gnome-weather gnome-maps \
            gnome-calendar gnome-clocks vlc dconf-cli xsettingsd \
            cava fastfetch flatpak libfuse2t64 zsh starship konsole \
            sddm kde-config-sddm sddm-theme-breeze \
            qml6-module-qt5compat-graphicaleffects qml6-module-qtquick-virtualkeyboard \
            binutils build-essential cmake extra-cmake-modules gettext pkg-config \
            qt6-base-dev qt6-base-dev-tools qt6-declarative-dev qt6-declarative-dev-tools qt6-shader-baker \
            libkf6config-dev libkf6coreaddons-dev libkf6globalaccel-dev libkf6i18n-dev \
            libkf6iconthemes-dev libkf6jobwidgets-dev libkf6kio-dev libkf6runner-dev libkf6service-dev \
            libkf6svg-dev libkf6windowsystem-dev libplasma-dev liblayershellqtinterface-dev \
            libplasmaactivities-dev libplasmaactivitiesstats-dev libappstreamqt-dev \
            plasma-workspace-dev libpipewire-0.3-dev

        # Ubuntu provides KPackage through these runtime, CLI, and development packages.
        sudo apt-get install -y --no-remove kpackagetool6 libkf6package6 libkf6package-dev

        # Install Plasma and GTK themes.
        theme=$(unpack plasma6macos-plasma-theme)
        copy_user "$theme" "$HOME/.local/share" plasma-theme
        theme=$(unpack plasma6macos-gtk-theme)
        copy_user "$theme" "$HOME/.themes" gtk-theme
        theme=$(unpack plasma6macos-kvantum-config)
        copy_user "$theme" "$HOME/.config/Kvantum" kvantum

        # Upstream Kubuntu 26.04 release; checksum from GitHub release metadata.
        darkly="$WORK/darkly-0.5.42_kubuntu-26.04_amd64.deb"
        curl --fail --location --retry 3 -o "$darkly" \
            https://github.com/Bali10050/Darkly/releases/download/v0.5.42/darkly-0.5.42_kubuntu-26.04_amd64.deb
        printf '%s  %s\n' 04d12406640f34f3042322c2958169e1cf2c51fe02fb933b493a171e44ea3312 "$darkly" | sha256sum --check
        sudo apt-get install -y --no-remove "$darkly"

        theme=$(unpack plasma6macos-icons)
        copy_user "$theme" "$HOME/.local/share/icons" icons
        theme=$(unpack plasma6macos-cursors)
        copy_user "$theme" "$HOME/.local/share/icons" cursors
        theme=$(unpack plasma6macos-fonts)
        copy_user "$theme" "$HOME/.local/share/fonts" fonts
        fc-cache -f
        theme=$(unpack plasma6macos-wallpapers)
        sudo python3 "$STATE_HELPER" "$BACKUP/system-state" "$HOME" copy \
            "$theme/usr/share/wallpapers" /usr/share/wallpapers
        sudo rsync -a --chown=root:root --backup --backup-dir="$BACKUP/system-wallpapers" \
            "$theme/usr/share/wallpapers/" /usr/share/wallpapers/
        theme=$(unpack plasma6macos-plasmoids)
        copy_user "$theme/plasmoids" "$HOME/.local/share/plasma/plasmoids" plasmoids
        theme=$(unpack plasma6macos-kwin-effect)
        copy_user "$theme/kwin" "$HOME/.local/share/kwin" kwin
        copy_user "$theme/wallpapers" "$HOME/.local/share/plasma/wallpapers" plasma-wallpapers

        # main requires newer KDE libraries; v1.9.6 supports those shipped with Ubuntu 26.04.
        git clone --depth 1 --branch v1.9.6 \
            https://github.com/xarbit/plasma6-applet-appgrid.git "$WORK/plasma6-applet-appgrid"
        cmake -S "$WORK/plasma6-applet-appgrid" -B "$WORK/appgrid-build" \
            -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr
        cmake --build "$WORK/appgrid-build" --parallel "$(nproc)"
        # Stage AppGrid so every installed file can be restored or removed precisely.
        (umask 022; DESTDIR="$WORK/appgrid-stage" cmake --install "$WORK/appgrid-build")
        sudo python3 "$STATE_HELPER" "$BACKUP/system-state" "$HOME" copy "$WORK/appgrid-stage/usr" /usr
        sudo rsync -a --chown=root:root "$WORK/appgrid-stage/usr/" /usr/

        install_punchi_dock

        theme=$(unpack plasma6macos-cava)
        copy_user "$theme" "$HOME/.config" cava
        theme=$(unpack plasma6macos-fastfetch)
        copy_user "$theme" "$HOME/.local/share/fastfetch" fastfetch

        # Keep the Flatpak remote, apps, and theme permissions in the user scope.
        flatpak --user remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
        flatpak --user install -y flathub \
            io.bassi.Amberol net.agalwood.Motrix com.rafaelmardojai.Blanket \
            com.github.KRTirtho.Spotube com.mattjakeman.ExtensionManager
        capture_user_path "$HOME/.local/share/flatpak/overrides/global"
        flatpak override --user --filesystem="$HOME/.local/share/icons:ro" \
            --filesystem="$HOME/.themes:ro" --filesystem=xdg-config/gtk-4.0:ro \
            --filesystem=xdg-config/gtk-3.0:ro

        # Preserve Ubuntu SDDM paths and settings; configure only the theme.
        theme=$(unpack plasma6macos-sddm)
        capture_system_path /usr/share/sddm/themes/tahoe-sddm
        capture_system_path /usr/share/sddm/themes/tahoe-sddm-dark
        capture_system_path /etc/sddm.conf.d/zz-macos-theme.conf
        sudo mkdir -p /usr/share/sddm/themes /etc/sddm.conf.d
        sudo rsync -a --chown=root:root --backup --backup-dir="$BACKUP/sddm-themes" \
            "$theme/tahoe-sddm" "$theme/tahoe-sddm-dark" /usr/share/sddm/themes/
        if sudo test -f /etc/sddm.conf.d/zz-macos-theme.conf; then
            sudo cp -a /etc/sddm.conf.d/zz-macos-theme.conf "$BACKUP/"
        fi
        printf '[Theme]\nCurrent=tahoe-sddm\n' | sudo tee /etc/sddm.conf.d/zz-macos-theme.conf >/dev/null
        # Ubuntu selects the display manager through debconf/dpkg-reconfigure.

    fi

    # The Firefox theme installer also supports Ubuntu Snap profiles.
    # SafariFox edits browser profiles; preserve their complete original state.
    for browser_dir in \
        .mozilla/firefox .config/mozilla/firefox snap/firefox/common/.mozilla/firefox \
        .var/app/org.mozilla.firefox/.mozilla/firefox .librewolf \
        .var/app/io.gitlab.librewolf-community/.librewolf .floorp \
        .var/app/one.ablaze.floorp/.floorp; do
        capture_user_path "$HOME/$browser_dir"
    done
    install_safarifox

    # Install Oh My Zsh without launching a shell or changing the login shell.
    capture_user_path "$HOME/.oh-my-zsh"
    capture_user_path "$HOME/.zshrc"
    capture_user_path "$HOME/.zshrc.pre-oh-my-zsh"
    if [[ ! -d $HOME/.oh-my-zsh ]]; then
        curl --fail --location --retry 3 \
            https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh \
            -o "$WORK/install-ohmyzsh.sh"
        RUNZSH=no CHSH=no KEEP_ZSHRC=yes sh "$WORK/install-ohmyzsh.sh" --unattended
    fi
    for plugin in zsh-autosuggestions zsh-syntax-highlighting zsh-history-substring-search; do
        clone_if_missing "https://github.com/zsh-users/$plugin.git" "$HOME/.oh-my-zsh/custom/plugins/$plugin"
    done
    # Each plugin uses its own repository and destination directory.
    theme=$(unpack plasma6macos-zshstarship-konsole)
    copy_user "$theme" "$HOME" zsh-konsole

    # Import the desktop layout after installing the applications.
    theme=$(unpack plasma6macos-gnome-config)
    dconf dump / > "$BACKUP/dconf.ini"
    mkdir -p "$BACKUP/dconf"
    dconf dump /org/gnome/ > "$BACKUP/dconf/gnome.ini"
    dconf dump /org/gtk/ > "$BACKUP/dconf/gtk.ini"
    touch "$BACKUP/dconf/ready"
    bash "$theme/plasma6macos-gnome-config.sh"
    theme=$(unpack plasma6macos-kde-config)
    # Exclude other distributions' settings and the original author's profile pictures.
    mkdir -p "$WORK/kde-config"
    rsync -a --exclude='conf-*/' --exclude='.face*' "$theme/" "$WORK/kde-config/"
    python3 "$SCRIPT_DIR/scripts/configure-punchi-dock.py" \
        "$WORK/kde-config/plasma-org.kde.plasma.desktop-appletsrc" \
        "$WORK/kde-config/punchi-dock" \
        "$WORK/kde-config/plasmashellrc"

    # Stop plasmashell so it cannot overwrite the new layout when the session ends.
    if systemctl --user is-active --quiet plasma-plasmashell.service; then
        systemctl --user stop plasma-plasmashell.service
    else
        kquitapp6 plasmashell
    fi
    PLASMA_STOPPED=1
    copy_user "$WORK/kde-config" "$HOME/.config" kde-config
    # The archive includes GTK 4 files; no directory removal or symlinks are needed.
    kwriteconfig6 --file kdeglobals --group Icons --key Theme MacTahoe
    kwriteconfig6 --file kdeglobals --group KDE --key widgetStyle kvantum
    kwriteconfig6 --file kcminputrc --group Mouse --key cursorTheme WhiteSur-cursors
    gsettings set org.gnome.desktop.interface cursor-theme WhiteSur-cursors
    gsettings set org.gnome.desktop.interface icon-theme MacTahoe
    gsettings set org.gnome.desktop.interface gtk-theme MacTahoe-Light
    gsettings set org.gnome.desktop.interface color-scheme default
    restart_plasma
    PLASMA_STOPPED=0

    echo "Done. Backups of overwritten files: $BACKUP"
    echo 'Log out and back into Plasma, or restart, to apply all appearance settings.'
    echo 'To use SDDM instead of GDM: sudo dpkg-reconfigure sddm (select sddm).'
    echo 'Optional: set Zsh as your login shell: chsh -s /usr/bin/zsh'
    echo 'The Plymouth boot theme is not installed by this script.'

    # Clean up before the session can be closed by a confirmed action.
    rm -rf -- "$WORK"
    record_inventory after
    touch "$BACKUP/installation-complete"
    trap - EXIT
    finish_installation
}

# Sourcing exposes helpers for tests without running the installer.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
