"""Punchi Dock build, panel conversion, and rollback contracts."""
import importlib.util
import configparser
import shutil
import json
from pathlib import Path
import unittest
import zipfile

from test_installer import PROJECT, Sandbox
from test_uninstall import file_state

spec = importlib.util.spec_from_file_location('configure_punchi', PROJECT / 'scripts/configure-punchi-dock.py')
layout_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout_module)
PLUGIN = 'org.kde.plasma.punchi-dock-remastered'


class PunchiTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)
        self.layout = self.box.root / 'layout'
        self.settings = self.box.root / 'dock-settings'
        with zipfile.ZipFile(PROJECT / 'sources/plasma6macos-kde-config.zip') as archive:
            self.original = archive.read('plasma6macos-kde-config/plasma-org.kde.plasma.desktop-appletsrc').decode()
        self.layout.write_text(self.original)
        self.shell = self.layout.with_name('plasmashellrc')
        with zipfile.ZipFile(PROJECT / 'sources/plasma6macos-kde-config.zip') as archive:
            self.original_shell = archive.read('plasma6macos-kde-config/plasmashellrc').decode()
        self.shell.write_text(self.original_shell)

    def build_dock(self, **env):
        return self.box.shell('''
WORK="$TEST_ROOT/build-work"
BACKUP="$TEST_ROOT/backup"
STATE_HELPER="$TEST_ROOT/project with spaces/scripts/file-state.py"
mkdir -p "$WORK" "$BACKUP"
source "$TEST_ROOT/project with spaces/scripts/state.sh"
python3 "$STATE_HELPER" "$BACKUP/user-state" "$HOME" init user
install_punchi_dock
''', **env)

    def configured_dock(self):
        config = layout_module.read_config(self.layout.read_text())
        docks = [section for section in config.sections() if config[section].get('plugin') == PLUGIN]
        self.assertEqual(len(docks), 1)
        dock = docks[0]
        panel = dock.rsplit('][Applets][', 1)[0]
        panel_id = panel.rsplit('][', 1)[-1]
        dock_id = dock.rsplit('][', 1)[-1]
        pins = json.loads((self.settings / f'dock_items_{dock_id}.json').read_text())
        return config, panel, dock, panel_id, pins

    def test_clean_bottom_panel_and_exact_pins_preserve_other_panels(self):
        layout_module.configure(self.layout, self.settings, directories=[])
        original = layout_module.read_config(self.original)
        configured, panel, dock, panel_id, pins = self.configured_dock()
        self.assertFalse(configured.has_section('Containments][27'))
        self.assertNotEqual(panel_id, '27')
        for section in original.sections():
            if section == 'Containments][27' or section.startswith('Containments][27]['):
                continue
            self.assertEqual(dict(original[section]), dict(configured[section]), section)
        children = [section for section in configured.sections()
                    if section.startswith(panel + '][Applets][') and section.count('][') == 3]
        self.assertEqual(len(children), 2)
        self.assertEqual({configured[section]['plugin'] for section in children},
                         {PLUGIN, 'dev.xarbit.appgrid'})
        order = configured[panel + '][General']['AppletOrder'].split(';')
        self.assertEqual(configured[f'{panel}][Applets][{order[0]}']['plugin'], 'dev.xarbit.appgrid')
        self.assertEqual([pin['storageId'] for pin in pins], [
            'org.gnome.Nautilus.desktop', 'org.kde.kcalc.desktop', 'org.kde.gwenview.desktop',
            'org.kde.elisa.desktop', 'org.kde.kate.desktop', 'org.kde.discover.desktop',
            'systemsettings.desktop'])
        self.assertTrue(all(pin['type'] == 'app' for pin in pins))
        self.assertEqual(pins[2]['icon'], 'graphics-image-viewer')
        raw = configured[dock + '][Configuration][General']['dockItemsJson']
        self.assertEqual(json.loads(raw), pins)
        first = self.layout.read_bytes(), self.shell.read_bytes()
        layout_module.configure(self.layout, self.settings, directories=[])
        self.assertEqual((self.layout.read_bytes(), self.shell.read_bytes()), first)

    def test_panel_height_position_width_alignment_visibility_opacity_and_floating(self):
        layout_module.configure(self.layout, self.settings, directories=[])
        config, panel, dock, panel_id, _ = self.configured_dock()
        self.assertEqual(config[panel]['location'], '4')
        self.assertEqual(config[panel]['formfactor'], '2')
        general = config[dock + '][Configuration][General']
        for key, value in {'panelThickness': '64', 'panelLengthMode': 'fitContent',
                           'panelAlignmentMode': 'center', 'panelVisibilityMode': 'dodgeWindows',
                           'panelOpacityMode': 'adaptive', 'panelFloatingMode': 'panelAndApplets'}.items():
            self.assertEqual(general[key], value, key)
        shell = layout_module.read_config(self.shell.read_text())
        view = f'PlasmaViews][Panel {panel_id}'
        for key, value in {'alignment': '132', 'panelLengthMode': '1', 'panelVisibility': '2',
                           'panelOpacity': '0', 'floating': '1', 'floatingApplets': '1'}.items():
            self.assertEqual(shell[view][key], value, key)
        self.assertEqual(shell[view + '][Defaults']['thickness'], '64')
        self.assertFalse(shell.has_section('PlasmaViews][Panel 27'))
        self.assertEqual(dict(shell['PlasmaViews][Panel 3']),
                         dict(layout_module.read_config(self.original_shell)['PlasmaViews][Panel 3']))

    def test_punchi_dot_indicator_bounce_click_and_popup_icons(self):
        layout_module.configure(self.layout, self.settings, directories=[])
        config, _, dock, _, pins = self.configured_dock()
        appearance = config[dock + '][Configuration][Appearance']
        self.assertEqual(appearance['indicatorType'], 'dot')
        for key in ('folderGridIconSize', 'folderListIconSize', 'folderDetailedIconSize', 'folderFanIconSize'):
            self.assertEqual(appearance[key], '48')
        self.assertEqual(config[dock + '][Configuration][Mouse']['clickEffect'], 'bounce')
        self.assertEqual(len(pins), 7)
        self.assertTrue(all(item['type'] == 'app' for item in pins))

    def test_desktop_names_and_icons_are_encoded_for_kconfig_and_json(self):
        apps = self.box.root / 'applications'
        apps.mkdir()
        (apps / 'org.gnome.Nautilus.desktop').write_text(
            '[Desktop Entry]\nName=Files "test" \\ path\nIcon=system-file-manager\n')
        (apps / 'org.kde.gwenview.desktop').write_text(
            '[Desktop Entry]\nName=Gwenview\nIcon=wrong-icon\n')
        layout_module.configure(self.layout, self.settings, directories=[apps])
        config, _, dock, _, pins = self.configured_dock()
        self.assertEqual(pins[0]['name'], 'Files "test" \\ path')
        self.assertEqual(pins[0]['icon'], 'system-file-manager')
        self.assertEqual(pins[2]['icon'], 'graphics-image-viewer')
        encoded = config[dock + '][Configuration][General']['dockItemsJson']
        self.assertEqual(json.loads(encoded.replace('\\\\', '\\')), pins)

    def test_no_bottom_panel_or_multiple_old_docks_create_one_clean_panel(self):
        missing = self.original.replace('location=4', 'location=3')
        duplicate = (self.original + '\n[Containments][500]\nplugin=org.kde.panel\nlocation=4\n'
                     '\n[Containments][500][Applets][501]\nplugin=org.kde.plasma.icontasks\n')
        for text in (missing, duplicate):
            with self.subTest(text=text[:30]):
                self.layout.write_text(text)
                self.shell.write_text(self.original_shell)
                shutil.rmtree(self.settings, ignore_errors=True)
                layout_module.configure(self.layout, self.settings, directories=[])
                config, panel, _, _, _ = self.configured_dock()
                bottoms = [section for section in config.sections()
                           if config[section].get('plugin') == 'org.kde.panel'
                           and config[section].get('location') == '4']
                self.assertEqual(bottoms, [panel])
                self.assertFalse(config.has_section('Containments][500'))

    def test_malformed_layout_is_rejected_before_any_file_is_written(self):
        self.layout.write_text('not a valid config')
        with self.assertRaises(configparser.Error):
            layout_module.configure(self.layout, self.settings, directories=[])
        self.assertEqual(self.layout.read_text(), 'not a valid config')
        self.assertEqual(self.shell.read_text(), self.original_shell)
        self.assertFalse(self.settings.exists())

    def test_build_updates_only_the_dock_and_rollback_restores_previous_version(self):
        dock = self.box.home / '.local/share/plasma/plasmoids' / PLUGIN
        dock.mkdir(parents=True)
        (dock / 'old-module').write_text('previous dock')
        sibling = dock.parent / 'unrelated-widget'
        sibling.mkdir()
        (sibling / 'keep').write_text('unrelated')
        config = self.box.home / '.config/punchi-dock'
        config.mkdir()
        (config / 'dock_items_28.json').write_text('previous settings')
        result = self.build_dock()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((dock / 'old-module').exists())
        self.assertTrue((dock / 'contents/ui/org/punchi/dock/libpunchidockintegration.so').exists())
        self.assertTrue((dock / 'LICENSE').exists())
        self.assertTrue((dock / 'NOTICE').exists())
        self.assertEqual((sibling / 'keep').read_text(), 'unrelated')
        # Model the native module persisting the newly installed configuration.
        (config / 'dock_items_28.json').write_text('new settings')
        state = file_state.Journal(self.box.root / 'backup/user-state', self.box.home)
        state.restore(apply=True, recovery=self.box.root / 'recovery')
        self.assertEqual((dock / 'old-module').read_text(), 'previous dock')
        self.assertFalse((dock / 'metadata.json').exists())
        self.assertEqual((config / 'dock_items_28.json').read_text(), 'previous settings')
        self.assertEqual((sibling / 'keep').read_text(), 'unrelated')
        log = self.box.log()
        self.assertIn('fetch --depth 1 origin 84c42df2462a411103b0bb53055d4a9a62a8fbb2', log)
        self.assertIn('-DPUNCHI_EMBED_QML_MODULE_IN_KPACKAGE=ON', log)
        self.assertIn('-DBUILD_TESTING=OFF', log)
        self.assertNotIn('sudo\t', log)
        self.assertNotIn('systemctl\t', log)

    def test_build_failure_and_incomplete_native_module_leave_existing_dock_untouched(self):
        dock = self.box.home / '.local/share/plasma/plasmoids' / PLUGIN
        dock.mkdir(parents=True)
        (dock / 'keep').write_text('previous dock')
        result = self.build_dock(TEST_PUNCHI_BUILD_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((dock / 'keep').read_text(), 'previous dock')
        # Retry in a fresh journal, like a fresh installation run.
        import shutil
        shutil.rmtree(self.box.root / 'backup')
        result = self.build_dock(TEST_PUNCHI_MISSING_MODULE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('expected package and native module', result.stderr)
        self.assertEqual((dock / 'keep').read_text(), 'previous dock')
        self.assertFalse((dock / 'metadata.json').exists())


if __name__ == '__main__':
    unittest.main()
