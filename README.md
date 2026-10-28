# macOS appearance for KDE Plasma on Ubuntu

This installer applies the bundled macOS-style themes and desktop layout to KDE Plasma 6 on Ubuntu/Kubuntu 26.04 LTS.

> Sources were downloaded from [Transform KDE Plasma 6 Look Like macOS](https://www.opendesktop.org/p/2304796).
><br>
> Script is based on [TRANSFORM KDE PLASMA 6.6 LOOK LIKE MACOS ON CACHYOS](https://www.youtube.com/watch?v=IybrdYGncPw).
><br>
> ***All commands were ported to Ubuntu ones.***

## Requirements

- Ubuntu or Kubuntu 26.04 LTS on amd64.
- An active KDE Plasma 6 desktop session with a working session D-Bus connection.
- A regular user account with sudo access, and Python 3 installed.
- An internet connection and the ZIP archives included in `sources/`.

If KDE is not installed, install it first:

```bash
sudo apt update
sudo apt install plasma-desktop plasma-workspace sddm
```

Log out, select a Plasma session on the login screen, and log back in before running the installer.

## Run

Save your work and close Firefox before installation. The installer replaces the current desktop layout and several application settings.

Run as your regular user, without prefixing the script with sudo:

```bash
bash ~/git/kde_plasma_to_macos/install.sh
```

The script resolves its own directory, so you can run it from any working directory. It requests sudo access for system changes.

If a run reaches Firefox/SafariFox and then fails, resume that stage using the original failed-install backup:

```bash
bash ~/git/kde_plasma_to_macos/install.sh --resume-firefox "$HOME/.local/state/kde-plasma-to-macos/backups/<timestamp>-<process-id>"
```

Use this only when the log confirms that the preceding stages (including Flatpak and SDDM) finished. Resume skips APT setup, theme extraction, AppGrid/Punchi compilation, and Flatpak/SDDM installation. It continues with Firefox, SafariFox, Zsh, and the desktop layout. It reuses the original rollback journals and package baseline instead of creating a backup of the partially installed appearance. Completed or restored backups, invalid journals, and package/Flatpak/Snap state that changed after the failed run are rejected before resuming.

For usage information:

```bash
bash ~/git/kde_plasma_to_macos/install.sh --help
```

## What it installs and configures

- APT packages from Ubuntu repositories, including Universe: theme tools, KDE build dependencies, GNOME applications, VLC, Cava, Fastfetch, Flatpak, Zsh, Starship, and SDDM.
- Bundled Plasma, GTK, Kvantum, icon, cursor, font, wallpaper, widget, and KWin assets.
- Darkly 0.5.42 for Kubuntu 26.04 amd64, with SHA-256 verification.
- AppGrid v1.9.6 built from source for compatibility with Ubuntu 26.04 KDE libraries.
- Punchi Dock Remastered built from pinned upstream sources, with a clean bottom panel and the seven application pins listed below.
- Amberol, Motrix, Blanket, Spotube, and Extension Manager through user-scoped Flathub, with read access to local theme directories.
- Firefox, if missing, before installing the SafariFox theme. Existing native, Snap, and user/system Flatpak installations are detected; otherwise the script runs `sudo apt-get install -y --no-remove firefox` (the Ubuntu package installs Firefox through Snap).
- The Tahoe SDDM theme, SafariFox Firefox theme, Oh My Zsh, Zsh plugins, and bundled terminal settings.
- The bundled Kubuntu panel layout and KDE/GNOME appearance settings.

Plasma Shell is briefly stopped and restarted while the desktop configuration is copied. The script stops if a command fails; package installations and earlier changes are not automatically rolled back.

## Firefox and SafariFox

An installed Firefox executable does not necessarily have a browser profile yet. Before applying SafariFox, the installer checks the selected native, Snap, or user/system Flatpak installation. If it has no profile, Firefox creates and registers `default-release` using `--headless --no-remote -CreateProfile default-release`, which exits after profile creation without opening a browser window.

Existing registered profiles are preserved, including custom profile names and paths within HOME. They are added to the rollback journal before the theme is applied. Profiles outside HOME are rejected because they cannot be safely restored by the existing user backup mechanism.

SafariFox runs from a temporary copy of its repository. A compatibility adapter uses the current HOME and registered `profiles.ini` paths and avoids the upstream `((installed++))` exit-status problem under `set -e`. The parent passes an explicit list of validated, backed-up profiles to the staged installer's per-profile theme function. Upstream browser re-detection with `snap list | grep -q` or Flatpak listings cannot redirect installation to a different profile directory. Each target profile path is printed before applying CSS. The downloaded checkout is left unchanged. If profile creation fails, the installer stops before applying the theme and can be resumed after Firefox is initialized.

## Punchi Dock Remastered

The installer builds [Punchi Dock Remastered](https://github.com/PunchiSoft/punchi-dock-remastered) from source version 0.9.7.84 at commit [`84c42df2462a411103b0bb53055d4a9a62a8fbb2`](https://github.com/PunchiSoft/punchi-dock-remastered/tree/84c42df2462a411103b0bb53055d4a9a62a8fbb2), using the installed Ubuntu Qt/KDE libraries. Build dependencies include the Qt Shader Baker, Plasma workspace headers, and PipeWire headers. The native build uses two parallel jobs.

The dock and its native QML module are staged first and installed together under:

```text
~/.local/share/plasma/plasmoids/org.kde.plasma.punchi-dock-remastered/
```

Translations are installed in `~/.local/share/locale/`. Upstream `LICENSE` and `NOTICE` files are preserved; Punchi Dock remains licensed under GPL-3.0-or-later, independently of this installer.

KPackage is installed system-wide using `sudo apt-get install -y --no-remove kpackagetool6 libkf6package6 libkf6package-dev`. These are the Ubuntu package names for its CLI, runtime, and development files. Nautilus, KCalc, Gwenview, Elisa, Kate, KDE Discover, and System Settings are installed so every configured pin has a corresponding application. Here, "app installer" means KDE Discover.

The installer removes the old bottom panels from the desktop configuration and creates a clean panel containing only **AppGrid Launcher Center** (`dev.xarbit.appgrid`) followed by Punchi Dock. Other panels are preserved. The old dock's installed widget files are retained, so it remains available through Add Widgets. Reapplying the preset reuses the new panel rather than creating duplicates.

| Panel setting | Value |
|---|---|
| Height | 64 px |
| Position | Bottom |
| Width | Fit content |
| Alignment | Center |
| Visibility | Dodge windows |
| Opacity | Adaptive |
| Floating | Panel and applets |

Punchi Dock contains exactly these pinned applications, in order: **Nautilus, KCalc, Gwenview, Elisa, Kate, KDE Discover, System Settings**. Firefox and Konsole remain installed but are not pinned by this preset. PunchiMenu, media player, separators, and calendar items are not added; the old bottom-panel calendar widget is also removed from the layout.

Gwenview uses the `graphics-image-viewer` icon. The window indicator shape is **Dot**, the mouse click effect is **Bounce**, and popup layout icon sizes are **48 px** for Grid, List, Detailed, and Fan layouts. The dock starts with Plasma as part of the saved panel layout; no separate autostart service is created.

The original dock directory, translations that are overwritten, `~/.config/punchi-dock/`, and `~/.local/share/punchi-dock-remastered/` are included in rollback bookkeeping. `uninstall.sh --apply` restores an existing local dock or removes the new one, and restores the previous panel configuration. The selected source version and commit are written to `punchi-dock-source.txt` in the installation backup.

## Restart or logout

After a successful installation, the script asks:

```text
Restart the computer now? [y/N]:
```

- Enter `Y` to restart immediately.
- Enter `N` or press Enter to continue to the logout question.

```text
Log out of the current Plasma session now? [y/N]:
```

- Enter `Y` to log out of the current Plasma session.
- Enter `N` or press Enter to keep working and apply the remaining settings later.

Both questions accept lowercase answers. Invalid input repeats the question. End of input declines the action. Restart and logout are requested only after an explicit `Y`; save your work first.

## Backups

Each run prints its backup directory:

```text
~/.local/state/kde-plasma-to-macos/backups/<timestamp>-<process-id>/
```

New installations record the original contents, permissions, and symlinks of managed files in `user-state/` and `system-state/` journals. They track newly created paths as well as overwritten files. AppGrid is staged before its system files are installed, so those files are tracked too. Existing browser profiles and Oh My Zsh settings are backed up before their installers run.

The backup also contains APT package versions and manual-install marks, user Flatpak refs/remotes, installed Snap names, and the original GNOME/GTK dconf settings. An after-install inventory is also written when installation stops with an error, allowing recorded partial installations to be undone. Older category-based backups are retained for compatibility.

Backup directories are private to your account. System snapshots may be owned by root. Browser profile snapshots can contain private browsing data and may require substantial disk space. Keep the backups until you no longer need to restore the original state.

## Uninstall and restore

Close Firefox and save your work. Use the same account and HOME directory that ran the installer. Preview restoration of the latest backup that has not already been restored:

```bash
bash ~/git/kde_plasma_to_macos/uninstall.sh
```

Apply that restoration:

```bash
bash ~/git/kde_plasma_to_macos/uninstall.sh --apply
```

The script displays the restoration summary and asks for Y/N confirmation. If it needs to remove SDDM while SDDM is running your desktop, it stops before making changes. Switch to a text console (for example, Ctrl+Alt+F3), log in, and run:

```bash
dbus-run-session bash ~/git/kde_plasma_to_macos/uninstall.sh --apply
```

The confirmation accepts Y or N. Enter or end of input declines. To choose a particular installation instead:

```bash
bash ~/git/kde_plasma_to_macos/uninstall.sh --backup "$HOME/.local/state/kde-plasma-to-macos/backups/<timestamp>-<process-id>" --apply
```

For new-format backups, restoration:

- Restores overwritten files, symlinks, permissions, browser profiles, and shell settings, and removes paths created by the installer.
- Restores GNOME/GTK dconf settings and the previous global Flatpak override.
- Removes only APT packages, Snap packages, Flatpak refs, and user Flatpak remotes recorded as newly added by that installation. An APT simulation rejects removal if it would also remove an originally installed package or an unrelated package added later. It does not run `autoremove` or purge existing package configuration.
- Restores the previous APT source files, SDDM theme configuration, and display-manager selection files, and reloads systemd configuration.
- Restarts Plasma after restoring desktop configuration, and marks the backup as restored to prevent accidentally applying it twice.

Before restoring files, the script saves their current state under:

```text
~/.local/state/kde-plasma-to-macos/recovery/<timestamp>-<process-id>/
```

Restoring a backup also reverts later edits to the managed files and browser profiles. The recovery copy preserves the pre-uninstall versions. It is a safety copy, not an automatic package-reinstallation mechanism.

### Limits

This is an installer rollback, not a complete system snapshot. Installer APT commands use `--no-remove` to reject dependency changes that would remove existing packages. Existing APT package upgrades are recorded but are not automatically downgraded: the previous package versions might no longer be available. Newly installed packages are removed without purging their distribution-generated configuration. Snap may retain automatic data snapshots, and a Snap or Flatpak remote still used by other software is retained. Downloaded source repositories, package caches, and unrelated changes made after installation are not removed.

If you changed your login shell to the newly installed Zsh, switch back to your previous login shell before uninstalling Zsh. If you manually changed the login shell with `chsh` or switched display managers with `dpkg-reconfigure` outside the installer, those extra actions are not separately tracked. Log out and back in after restoration; a reboot may be needed for a display-manager change to take effect.

Backups created before rollback journaling was added can restore only the saved overwritten files and dconf values. The uninstaller reports this limitation and does not guess which packages or new files to delete. Missing snapshots, inventories, or a HOME mismatch stop new-format restoration before file changes.

## Optional configuration

To select SDDM instead of GDM, run this command and choose `sddm`:

```bash
sudo dpkg-reconfigure sddm
```

The installer does not forcibly switch the running display manager.

To make Zsh your login shell:

```bash
chsh -s /usr/bin/zsh
```

The Plymouth boot theme is not installed by this script.

## Validation

Install the test tools on Ubuntu 26.04:

```bash
sudo apt install python3 shellcheck rsync unzip
```

Run the checks as a regular user:

```bash
bash ~/git/kde_plasma_to_macos/tests/check.sh
```

This checks Bash syntax, runs ShellCheck, and executes the Python standard-library test suite. Tests cover:

- Usage and environment checks before installation.
- Y/N answers, empty input, invalid answers, and end of input for restart and logout.
- Archives with and without wrapper directories, and corrupt archive failures.
- A complete simulated installation using the bundled ZIP archives, including the Kubuntu layout and configuration backups.
- Checksum failure, stopping on errors, temporary-file cleanup, and restarting Plasma after a failed configuration copy.
- Existing repositories, repeated asset copies, and the Plasma startup fallback.
- Existing and missing Firefox installations, installation failures, and installation order before SafariFox.
- Missing Firefox profiles across native/Snap/Flatpak installs, registered custom profiles, SafariFox's first-success counter, and resuming the failed Firefox stage with the original backup.
- Install/uninstall round trips, preview and confirmation, legacy backups, recovery copies, and duplicate-restore prevention.
- Original permissions and symlinks, removal of new paths, unrelated-file preservation, incomplete backups, and parent-symlink escapes.
- Package/ref removal plans and protection of originally installed APT packages.
- Punchi Dock package staging, embedded native-module checks, failed builds, clean-panel creation, all requested panel/appearance settings, exact application pins, and restoration of an existing dock without touching other installed widgets.

Tests use temporary HOME and project directories, including paths with spaces. Real file restoration is tested inside those temporary directories. Network, package, privileged, and desktop commands are replaced with test doubles. They do not install desktop packages, change your session, restart the computer, or download themes. They do not validate actual upstream downloads, AppGrid compilation, or the rendered desktop appearance.

## GitHub Actions

The workflow in `.github/workflows/ci.yml` runs on pushes, pull requests, and manual dispatch. It uses an Ubuntu 26.04 container, installs test tools, and runs `tests/check.sh` as an unprivileged user. The workflow only requests read access to repository contents and does not require repository secrets.

Keep this directory as the repository root when publishing to GitHub so that `.github/workflows/ci.yml`, `install.sh`, `tests/`, and `sources/` are in the expected locations.
