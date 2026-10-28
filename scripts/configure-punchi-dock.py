#!/usr/bin/env python3
"""Create a clean bottom panel with the requested Punchi Dock preset."""
import argparse
import configparser
import json
import os
from pathlib import Path
import re
import sys

PLUGIN = 'org.kde.plasma.punchi-dock-remastered'
APPGRID = 'dev.xarbit.appgrid'  # AppGrid Launcher Center, not the panel-popup variant.
PINNED_DESKTOP_IDS = (
    'org.gnome.Nautilus.desktop', 'org.kde.kcalc.desktop', 'org.kde.gwenview.desktop',
    'org.kde.elisa.desktop', 'org.kde.kate.desktop', 'org.kde.discover.desktop',
    'systemsettings.desktop',
)
GENERAL_SETTINGS = {
    'iconSize': '42', 'hoverScale': '1.65', 'showActiveTasks': 'true',
    'showRecentApplications': 'false', 'panelThickness': '64',
    'panelLengthMode': 'fitContent', 'panelAlignmentMode': 'center',
    'panelVisibilityMode': 'dodgeWindows', 'panelOpacityMode': 'adaptive',
    'panelFloatingMode': 'panelAndApplets',
}
APPEARANCE_SETTINGS = {
    'indicatorType': 'dot', 'folderGridIconSize': '48', 'folderListIconSize': '48',
    'folderDetailedIconSize': '48', 'folderFanIconSize': '48',
}
# Plasma 6 enums: Qt.AlignCenter=132, FitContent=1, DodgeWindows=2, Adaptive=0.
PANEL_VIEW_SETTINGS = {
    'alignment': '132', 'panelLengthMode': '1', 'panelVisibility': '2',
    'panelOpacity': '0', 'floating': '1', 'floatingApplets': '1',
    'shell': 'org.kde.plasma.desktop',
}


def read_config(text):
    config = configparser.ConfigParser(interpolation=None, delimiters=('=',))
    config.optionxform = str
    config.read_string(text)
    return config


def application_directories():
    home = Path.home()
    data_roots = [home / '.local/share', *map(Path, os.environ.get(
        'XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':'))]
    return [*(p / 'applications' for p in data_roots),
            Path('/var/lib/snapd/desktop/applications'),
            home / '.local/share/flatpak/exports/share/applications',
            Path('/var/lib/flatpak/exports/share/applications')]


def dock_items(launchers, directories):
    items = []
    seen = set()
    for launcher in launchers.split(','):
        if not launcher.strip():
            continue
        if not launcher.startswith('applications:'):
            raise ValueError(f'Unsupported pinned launcher: {launcher}')
        storage_id = launcher.removeprefix('applications:')
        if not re.fullmatch(r'[A-Za-z0-9_.+-]+\.desktop', storage_id):
            raise ValueError(f'Invalid desktop file ID: {storage_id}')
        if storage_id in seen:
            continue
        seen.add(storage_id)
        app_id = storage_id.removesuffix('.desktop')
        item = {'type': 'app', 'name': app_id, 'icon': 'application-x-executable',
                'storageId': storage_id, 'appId': app_id}
        for directory in directories:
            path = directory / storage_id
            if not path.is_file():
                continue
            desktop = read_config(path.read_text())
            if desktop.has_section('Desktop Entry'):
                item['name'] = desktop['Desktop Entry'].get('Name', app_id)
                item['icon'] = desktop['Desktop Entry'].get('Icon', item['icon'])
            break
        if storage_id == 'org.kde.gwenview.desktop':
            item['icon'] = 'graphics-image-viewer'
        items.append(item)
    if not items:
        raise ValueError('The bottom task manager has no pinned applications')
    return items


def sections_text(groups):
    return ''.join(f'[{name}]\n' + ''.join(f'{key}={value}\n' for key, value in values.items())
                   + '\n' for name, values in groups.items())


def replace_groups(text, removed_roots, groups):
    """Preserve all text outside the selected groups, including unknown settings."""
    headers = list(re.finditer(r'^\[([^\n]+)\]\r?$', text, re.MULTILINE))
    output = [text[:headers[0].start()] if headers else text]
    for index, header in enumerate(headers):
        section = header.group(1)
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        if not any(section == root or section.startswith(root + '][') for root in removed_roots):
            output.append(text[header.start():end])
    return ''.join(output).rstrip() + '\n\n' + sections_text(groups)


def configure(layout, settings_directory, directories=None, plasmashell=None):
    text = layout.read_text()
    config = read_config(text)
    shell_path = plasmashell if plasmashell is not None else layout.with_name('plasmashellrc')
    shell_text = shell_path.read_text() if shell_path.exists() else ''
    shell_config = read_config(shell_text)  # Validate both inputs before writing either one.
    bottom_panels = [section for section in config.sections()
                     if re.fullmatch(r'Containments\]\[\d+', section)
                     and config[section].get('plugin') == 'org.kde.panel'
                     and config[section].get('location') == '4']
    existing = []
    for panel in bottom_panels:
        children = [section for section in config.sections()
                    if re.fullmatch(re.escape(panel) + r'\]\[Applets\]\[\d+', section)]
        docks = [child for child in children if config[child].get('plugin') == PLUGIN]
        grids = [child for child in children if config[child].get('plugin') == APPGRID]
        if len(docks) == len(grids) == 1:
            existing.append((panel, grids[0], docks[0]))
    if len(existing) == 1:
        # Reapply the same preset without creating another panel on subsequent runs.
        panel, grid, dock = existing[0]
        panel_id, grid_id, dock_id = [value.rsplit('][', 1)[-1] for value in (panel, grid, dock)]
    else:
        used_ids = [int(value) for section in config.sections()
                    for value in re.findall(r'(?:Containments|Applets)\]\[(\d+)', section)]
        used_ids += [int(match.group(1)) for section in shell_config.sections()
                     if (match := re.match(r'PlasmaViews\]\[Panel (\d+)(?:\]\[|$)', section))]
        next_id = max(used_ids, default=0) + 1
        panel_id, grid_id, dock_id = map(str, range(next_id, next_id + 3))
        panel = f'Containments][{panel_id}'
        grid = f'{panel}][Applets][{grid_id}'
        dock = f'{panel}][Applets][{dock_id}'
    items = dock_items(','.join(f'applications:{app}' for app in PINNED_DESKTOP_IDS),
                       directories if directories is not None else application_directories())
    raw_json = json.dumps(items, ensure_ascii=False, separators=(',', ':'))
    # KConfig QString entries escape literal backslashes independently of JSON.
    encoded_json = raw_json.replace('\\', '\\\\')
    screen = config[bottom_panels[0]].get('lastScreen', '0') if bottom_panels else '0'
    groups = {
        panel: {'activityId': '', 'formfactor': '2', 'immutability': '1', 'lastScreen': screen,
                'location': '4', 'plugin': 'org.kde.panel'},
        panel + '][General': {'AppletOrder': f'{grid_id};{dock_id}'},
        grid: {'immutability': '1', 'plugin': APPGRID},
        grid + '][Configuration][General': {'customButtonImage': 'view-app-grid',
                                           'useCustomButtonImage': 'true'},
        dock: {'immutability': '1', 'plugin': PLUGIN},
        dock + '][Configuration][General': {'dockItemsJson': encoded_json, **GENERAL_SETTINGS},
        dock + '][Configuration][Appearance': APPEARANCE_SETTINGS,
        dock + '][Configuration][Mouse': {'clickEffect': 'bounce'},
    }
    removed_views = [f'PlasmaViews][Panel {root.rsplit("][", 1)[-1]}' for root in bottom_panels]
    view = f'PlasmaViews][Panel {panel_id}'
    views = {view: PANEL_VIEW_SETTINGS, view + '][Defaults': {'thickness': '64'}}
    new_layout = replace_groups(text, bottom_panels, groups)
    new_shell = replace_groups(shell_text, removed_views, views)
    settings_directory.mkdir(parents=True, exist_ok=True)
    (settings_directory / f'dock_items_{dock_id}.json').write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + '\n')
    layout.write_text(new_layout)
    shell_path.write_text(new_shell)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout', type=Path)
    parser.add_argument('settings_directory', type=Path)
    parser.add_argument('plasmashell', type=Path, nargs='?')
    args = parser.parse_args()
    configure(args.layout, args.settings_directory, plasmashell=args.plasmashell)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, configparser.Error) as error:
        print(f'Punchi Dock layout error: {error}', file=sys.stderr)
        sys.exit(1)
