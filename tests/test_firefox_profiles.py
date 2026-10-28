"""SafariFox regression tests: installed Firefox without an initialized profile."""
import subprocess
import unittest
from pathlib import Path

from test_installer import PROJECT, Sandbox


class FirefoxProfileTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)

    def install_theme(self, box=None, **env):
        box = box or self.box
        return box.shell('''
SCRIPT_DIR="$TEST_ROOT/project with spaces"
SOURCES="$SCRIPT_DIR/sources"
WORK="$TEST_ROOT/work"
BACKUP="$HOME/.local/state/kde-plasma-to-macos/backups/profile-test"
STATE_HELPER="$SCRIPT_DIR/scripts/file-state.py"
mkdir -p "$WORK" "$BACKUP"
source "$SCRIPT_DIR/scripts/state.sh"
python3 "$STATE_HELPER" "$BACKUP/user-state" "$HOME" init user
for root in .mozilla/firefox .config/mozilla/firefox snap/firefox/common/.mozilla/firefox .var/app/org.mozilla.firefox/.mozilla/firefox; do
    capture_user_path "$HOME/$root"
done
install_safarifox
''', **env)

    def test_first_profile_is_created_for_native_snap_and_flatpak_firefox(self):
        cases = [
            ('native', '.mozilla/firefox'),
            ('snap', 'snap/firefox/common/.mozilla/firefox'),
            ('flatpak-user', '.var/app/org.mozilla.firefox/.mozilla/firefox'),
            ('flatpak-system', '.var/app/org.mozilla.firefox/.mozilla/firefox'),
        ]
        for kind, root in cases:
            with self.subTest(kind=kind):
                box = Sandbox()
                self.addCleanup(box.close)
                result = self.install_theme(box, TEST_FIREFOX=kind)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('SafariFox installed to', result.stdout)
                self.assertTrue((box.home / root / 'profiles.ini').exists())
                self.assertTrue((box.home / root / 'test.default-release/chrome/userChrome.css').exists())
                self.assertEqual(box.log().count('-CreateProfile default-release'), 1)
                self.assertNotIn('((installed+=1))', (box.sources / 'safarifox-theme/install.sh').read_text())

    def test_snap_profile_is_used_when_upstream_listing_misses_the_browser(self):
        result = self.install_theme(TEST_FIREFOX='snap', TEST_BROKEN_SAFARIFOX_DETECTION='1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        root = self.box.home / 'snap/firefox/common/.mozilla/firefox'
        self.assertTrue((root / 'test.default-release/chrome/userChrome.css').exists())
        self.assertFalse((self.box.home / '.mozilla/firefox').exists())
        self.assertIn(str(root), result.stdout)
        original = self.box.sources / 'safarifox-theme/install.sh'
        self.assertIn('snap list 2>/dev/null | grep -q firefox', original.read_text())
        # The staged installer must also fail closed if its explicit list is missing.
        stage = self.box.root / 'work/safarifox-theme/install.sh'
        result = subprocess.run(['bash', str(stage), '-f'], env=self.box.env,
                                text=True, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires an explicit', result.stderr)

    def test_modern_native_profile_location_is_detected(self):
        result = self.install_theme(TEST_NATIVE_PROFILE_ROOT='.config/mozilla/firefox')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.box.home / '.config/mozilla/firefox/test.default-release/chrome/userChrome.css').exists())

    def test_registered_custom_profile_is_used_without_creating_another(self):
        root = self.box.home / '.mozilla/firefox'
        root.mkdir(parents=True)
        custom = self.box.home / 'custom browser profile'
        custom.mkdir()
        (root / 'profiles.ini').write_text(
            f'[Profile0]\nName=custom\nIsRelative=0\nPath={custom}\nDefault=1\n')
        result = self.install_theme()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('-CreateProfile', self.box.log())
        self.assertTrue((custom / 'chrome/userChrome.css').exists())
        # A rollback must also cover registered profiles outside the usual Firefox root.
        helper = self.box.project / 'scripts/file-state.py'
        journal = self.box.home / '.local/state/kde-plasma-to-macos/backups/profile-test/user-state'
        result = subprocess.run(
            ['python3', str(helper), str(journal), str(self.box.home), 'restore', '--apply',
             '--recovery', str(self.box.root / 'recovery')], env=self.box.env,
            text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(custom.exists())
        self.assertFalse((custom / 'chrome').exists())

    def test_profile_creation_failure_stops_before_theme_changes(self):
        result = self.install_theme(TEST_PROFILE_CREATE_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('git\tclone', self.box.log())
        self.assertFalse((self.box.home / '.mozilla').exists())

    def test_profile_outside_home_is_rejected_without_theme_changes(self):
        root = self.box.home / '.mozilla/firefox'
        root.mkdir(parents=True)
        outside = self.box.root / 'outside-home'
        outside.mkdir()
        (root / 'profiles.ini').write_text(
            f'[Profile0]\nName=custom\nIsRelative=0\nPath={outside}\n')
        result = self.install_theme()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('outside the supported HOME', result.stderr)
        self.assertFalse((outside / 'chrome').exists())

    def test_failed_install_can_resume_at_firefox_using_original_backup(self):
        result = self.box.run(TEST_PROFILE_CREATE_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        backups = list((self.box.home / '.local/state/kde-plasma-to-macos/backups').iterdir())
        self.assertEqual(len(backups), 1)
        backup = backups[0]
        original = (backup / 'packages-before.tsv').read_text()
        self.assertTrue((backup / 'punchi-dock-source.txt').exists())
        after = (backup / 'packages-after.tsv').read_text()
        (backup / 'packages-after.tsv').write_text('changed-package\t2\n')
        (self.box.root / 'commands.log').unlink()
        result = self.box.run(['--resume-firefox', str(backup)], answers='N\nN\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('refusing an unsafe resume', result.stderr)
        self.assertNotIn('cmake\t', self.box.log())
        (backup / 'packages-after.tsv').write_text(after)
        (self.box.root / 'commands.log').unlink()
        result = self.box.run(['--resume-firefox', str(backup)], answers='N\nN\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SafariFox installed to', result.stdout)
        self.assertNotIn('cmake\t', self.box.log())
        self.assertNotIn('flatpak\t--user install', self.box.log())
        self.assertEqual((backup / 'packages-before.tsv').read_text(), original)
        self.assertTrue((backup / 'installation-complete').exists())
        self.assertTrue((self.box.home / '.config/plasma-org.kde.plasma.desktop-appletsrc').exists())
        self.assertEqual(len(list(backup.parent.iterdir())), 1)
        result = self.box.run(['--resume-firefox', str(backup)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Resume requires', result.stderr)


if __name__ == '__main__':
    unittest.main()
