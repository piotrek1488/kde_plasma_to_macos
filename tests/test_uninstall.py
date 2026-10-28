"""Round-trip rollback tests; no live package, network, or desktop operations."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from test_installer import PROJECT, Sandbox

spec = importlib.util.spec_from_file_location('file_state', PROJECT / 'scripts/file-state.py')
file_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(file_state)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)
        self.journal = file_state.Journal(self.box.root / 'journal', self.box.home, 'user')
        self.recovery = self.box.root / 'recovery'

    def test_restore_files_new_directories_symlinks_and_permissions(self):
        old = self.box.home / 'settings'
        old.write_text('original settings')
        old.chmod(0o640)
        link = self.box.home / 'link'
        link.symlink_to('settings')
        self.journal.capture(old)
        self.journal.capture(link)
        self.journal.capture(self.box.home / 'new/sub/file')
        old.write_text('changed settings')
        old.chmod(0o600)
        link.unlink()
        link.write_text('changed link')
        (self.box.home / 'new/sub').mkdir(parents=True)
        (self.box.home / 'new/sub/file').write_text('new data')
        self.journal.restore(apply=True, recovery=self.recovery)
        self.assertEqual(old.read_text(), 'original settings')
        self.assertEqual(old.stat().st_mode & 0o777, 0o640)
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), 'settings')
        self.assertFalse((self.box.home / 'new').exists())
        # The recovery journal can restore the state from immediately before uninstall.
        current = file_state.Journal(self.recovery, self.box.home)
        current.restore(apply=True, recovery=self.box.root / 'second-recovery')
        self.assertEqual(old.read_text(), 'changed settings')
        self.assertEqual(link.read_text(), 'changed link')
        self.assertEqual((self.box.home / 'new/sub/file').read_text(), 'new data')

    def test_copy_preserves_unrelated_files_and_original_baseline_across_repeated_copies(self):
        source = self.box.root / 'source'
        source.mkdir()
        (source / 'settings').write_text('theme')
        (source / 'new').write_text('new asset')
        target = self.box.home / 'target'
        target.mkdir()
        (target / 'settings').write_text('before')
        (target / 'unrelated').write_text('keep me')
        self.journal.capture_copy(source, target)
        shutil.copytree(source, target, dirs_exist_ok=True)
        self.journal.capture_copy(source, target)
        self.journal.restore(apply=True, recovery=self.recovery)
        self.assertEqual((target / 'settings').read_text(), 'before')
        self.assertEqual((target / 'unrelated').read_text(), 'keep me')
        self.assertFalse((target / 'new').exists())

    def test_missing_snapshot_stops_before_any_changes(self):
        target = self.box.home / 'original'
        target.write_text('before')
        self.journal.capture(target)
        target.write_text('after')
        (self.journal.directory / '0').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing backup'):
            self.journal.restore(apply=True, recovery=self.recovery)
        self.assertEqual(target.read_text(), 'after')

    def test_external_paths_and_parent_symlink_escape_are_rejected(self):
        external = self.box.root / 'external'
        external.mkdir()
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.journal.capture(external / 'file')
        (self.box.home / 'escape').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.journal.capture(self.box.home / 'escape/file')
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.journal.capture(self.box.home)

    def test_wrong_home_and_invalid_metadata_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'HOME'):
            file_state.Journal(self.journal.directory, self.box.root / 'other-home')
        target = self.box.home / 'original'
        target.write_text('before')
        self.journal.capture(target)
        del self.journal.data['entries'][0]['mode']
        target.write_text('after')
        with self.assertRaisesRegex(ValueError, 'metadata'):
            self.journal.restore(apply=True, recovery=self.recovery)
        self.assertEqual(target.read_text(), 'after')

    def test_preview_does_not_change_current_files(self):
        target = self.box.home / 'original'
        target.write_text('before')
        self.journal.capture(target)
        target.write_text('after')
        self.journal.restore()
        self.assertEqual(target.read_text(), 'after')
        self.assertFalse(self.recovery.exists())


@unittest.skipIf(os.geteuid() == 0, 'Run as a regular user')
class UninstallerTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)
        self.backup = self.box.home / '.local/state/kde-plasma-to-macos/backups/20260101-test'
        self.backup.mkdir(parents=True)
        file_state.Journal(self.backup / 'user-state', self.box.home, 'user')
        file_state.Journal(self.backup / 'system-state', self.box.home, 'system')
        (self.backup / 'rollback-version').write_text('1\n')
        for name in ('packages-before.tsv', 'packages-after.tsv', 'manual-before.txt',
                     'manual-after.txt', 'flatpak-before.txt', 'flatpak-after.txt',
                     'remotes-before.txt', 'remotes-after.txt',
                     'firefox-snap-before.txt', 'firefox-snap-after.txt', 'snaps-before.txt',
                     'snaps-after.txt', 'inventory-before-complete', 'inventory-after-complete'):
            (self.backup / name).write_text('')

    def run_uninstall(self, *args, answers='', **env):
        return subprocess.run(
            ['bash', str(self.box.project / 'uninstall.sh'), *args],
            env=self.box.env | env, cwd=self.box.root, input=answers, text=True,
            capture_output=True, timeout=120,
        )

    def make_changed_file(self):
        target = self.box.home / 'original'
        target.write_text('before')
        state = file_state.Journal(self.backup / 'user-state', self.box.home)
        state.capture(target)
        target.write_text('after')
        return target

    def test_default_preview_and_declined_apply_leave_files_unchanged(self):
        target = self.make_changed_file()
        for args, answers in [((), ''), (('--apply',), 'N\n')]:
            result = self.run_uninstall(*args, answers=answers)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(target.read_text(), 'after')
            self.assertFalse((self.backup / 'restored').exists())
            self.assertNotIn('apt-get remove', self.box.log())

    def test_apply_restores_and_keeps_recovery_and_prevents_duplicate_restore(self):
        target = self.make_changed_file()
        result = self.run_uninstall('--apply', answers='Y\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.read_text(), 'before')
        self.assertTrue((self.backup / 'restored').exists())
        recovery = list((self.box.home / '.local/state/kde-plasma-to-macos/recovery').iterdir())
        self.assertEqual(len(recovery), 1)
        manifest = json.loads((recovery[0] / 'user-state/manifest.json').read_text())
        self.assertTrue(manifest['entries'])
        result = self.run_uninstall('--apply', '--backup', str(self.backup), answers='Y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already been restored', result.stderr)

    def test_only_new_packages_refs_and_remotes_are_removed(self):
        (self.backup / 'packages-before.tsv').write_text('existing\t1\n')
        (self.backup / 'packages-after.tsv').write_text('existing\t2\nnew-package\t1\n')
        (self.backup / 'manual-after.txt').write_text('existing\nnew-package\n')
        (self.backup / 'flatpak-before.txt').write_text('app/existing/x86_64/stable\n')
        (self.backup / 'flatpak-after.txt').write_text('app/existing/x86_64/stable\napp/new/x86_64/stable\n')
        (self.backup / 'remotes-after.txt').write_text('flathub\n')
        (self.backup / 'firefox-snap-after.txt').write_text('installed\n')
        (self.backup / 'snaps-after.txt').write_text('firefox\n')
        result = self.run_uninstall('--apply', answers='Y\n', TEST_FIREFOX='snap')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = self.box.log()
        self.assertIn('sudo\tapt-get remove -y --no-auto-remove -- new-package\n', log)
        self.assertNotIn('-- existing', log)
        self.assertIn('sudo\tapt-mark auto existing\n', log)
        self.assertIn('flatpak\t--user uninstall -y --noninteractive --no-related -- app/new/x86_64/stable\n', log)
        self.assertIn('sudo\tsnap remove firefox\n', log)

    def test_apt_plan_cannot_remove_originally_installed_package(self):
        target = self.make_changed_file()
        (self.backup / 'packages-before.tsv').write_text('existing\t1\n')
        (self.backup / 'packages-after.tsv').write_text('existing\t1\nnew-package\t1\n')
        result = self.run_uninstall('--apply', answers='Y\n', TEST_APT_REMOVE_ORIGINAL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('originally installed', result.stderr)
        self.assertEqual(target.read_text(), 'after')
        self.assertNotIn('sudo\tapt-get remove -y', self.box.log())

    def test_removing_running_display_manager_requires_a_text_console(self):
        (self.backup / 'packages-after.tsv').write_text('sddm\t1\n')
        result = self.run_uninstall('--apply', answers='Y\n', XDG_SESSION_TYPE='wayland')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('terminate this desktop session', result.stderr)
        self.assertNotIn('sudo\tapt-get remove', self.box.log())

    def test_incomplete_inventory_is_rejected(self):
        target = self.make_changed_file()
        (self.backup / 'packages-after.tsv').unlink()
        result = self.run_uninstall('--apply', answers='Y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Incomplete inventory', result.stderr)
        self.assertEqual(target.read_text(), 'after')

    def test_legacy_backup_restores_available_files_without_removing_new_files(self):
        (self.backup / 'rollback-version').unlink()
        (self.backup / 'kde-config').mkdir()
        (self.backup / 'kde-config/kdeglobals').write_text('legacy desktop')
        (self.box.home / '.config/keep-new').write_text('cannot infer ownership')
        result = self.run_uninstall('--apply', answers='Y\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.box.home / '.config/kdeglobals').read_text(), 'legacy desktop')
        self.assertTrue((self.box.home / '.config/keep-new').exists())
        self.assertIn('only overwritten files', result.stdout)
        self.assertNotIn('apt-get remove', self.box.log())

    def test_partial_failed_installation_can_be_restored(self):
        shutil.rmtree(self.backup)
        result = self.box.run(TEST_BAD_CHECKSUM='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.box.home / '.themes').exists())
        result = self.run_uninstall('--apply', answers='Y\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.box.home / '.themes').exists())
        self.assertEqual((self.box.home / '.zshrc').read_text(), 'OLD ZSH SETTINGS\n')

    def test_install_then_uninstall_restores_original_desktop_and_shell(self):
        shutil.rmtree(self.backup)
        result = self.box.run(answers='N\nN\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.run_uninstall('--apply', answers='Y\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.box.home / '.config/kdeglobals').read_text(), 'OLD KDE SETTINGS\n')
        self.assertEqual((self.box.home / '.zshrc').read_text(), 'OLD ZSH SETTINGS\n')
        self.assertFalse((self.box.home / '.themes').exists())
        self.assertFalse((self.box.home / '.oh-my-zsh').exists())
        self.assertFalse((self.box.home / '.config/cava').exists())
        self.assertFalse((self.box.home / '.local/share').exists())


if __name__ == '__main__':
    unittest.main()
