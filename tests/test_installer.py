"""Offline installer tests. All system, network, and desktop actions are mocked."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT / 'install.sh'


class Sandbox:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kde-macos-tests-')
        self.root = Path(self.temp.name)
        # Exercise paths containing spaces and execution from another directory.
        self.project = self.root / 'project with spaces'
        self.sources = self.project / 'sources'
        self.sources.mkdir(parents=True)
        shutil.copyfile(INSTALLER, self.project / 'install.sh')
        shutil.copyfile(PROJECT / 'uninstall.sh', self.project / 'uninstall.sh')
        shutil.copytree(PROJECT / 'scripts', self.project / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        for archive in (PROJECT / 'sources').glob('*.zip'):
            (self.sources / archive.name).symlink_to(archive)
        self.home = self.root / 'home'
        (self.home / '.config').mkdir(parents=True)
        (self.home / '.config/kdeglobals').write_text('OLD KDE SETTINGS\n')
        (self.home / '.zshrc').write_text('OLD ZSH SETTINGS\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        mock = self.bin / 'mock-command'
        shutil.copyfile(PROJECT / 'tests/mock-command.sh', mock)
        mock.chmod(0o755)
        for name in (
            'plasmashell', 'dpkg', 'sudo', 'git', 'curl', 'sha256sum', 'cmake',
            'flatpak', 'gsettings', 'dconf', 'systemctl', 'kstart', 'kquitapp6',
            'kwriteconfig6', 'fc-cache', 'rsync', 'qdbus6', 'firefox', 'snap', 'dpkg-query', 'apt-mark',
        ):
            (self.bin / name).symlink_to(mock.name)
        # Do not inherit user configuration or shell startup hooks.
        self.env = {
            'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.home),
            'TMPDIR': str(self.root), 'TEST_ROOT': str(self.root),
            'XDG_CURRENT_DESKTOP': 'KDE', 'DBUS_SESSION_BUS_ADDRESS': 'test',
            'LANG': 'C.UTF-8',
        }

    def run(self, args=(), answers='', **env):
        return subprocess.run(
            ['bash', str(self.project / 'install.sh'), *args],
            env=self.env | env, cwd=self.root, input=answers,
            text=True, capture_output=True, timeout=120,
        )

    def shell(self, body, answers='', **env):
        return subprocess.run(
            ['bash', '-c', 'source "$1"\n' + body, 'test', str(INSTALLER)],
            env=self.env | env, cwd=self.root, input=answers,
            text=True, capture_output=True, timeout=30,
        )

    def log(self):
        path = self.root / 'commands.log'
        return path.read_text() if path.exists() else ''

    def close(self):
        self.temp.cleanup()


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)

    def test_source_does_not_run_installer(self):
        result = self.box.shell('echo imported')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'imported\n')
        self.assertEqual(self.box.log(), '')
        self.assertFalse((self.box.home / '.local').exists())

    def test_existing_firefox_is_not_reinstalled(self):
        for installation in ('native', 'snap', 'flatpak-user', 'flatpak-system'):
            with self.subTest(installation=installation):
                (self.box.root / 'commands.log').unlink(missing_ok=True)
                result = self.box.shell('ensure_firefox', TEST_FIREFOX=installation)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('sudo\t', self.box.log())

    def test_missing_firefox_is_installed(self):
        result = self.box.shell('ensure_firefox', TEST_FIREFOX='missing')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('sudo\tapt-get install -y --no-remove firefox\n', self.box.log())

    def test_firefox_install_failure_stops_before_theme(self):
        result = self.box.shell(
            'ensure_firefox\necho SHOULD_NOT_INSTALL_THEME',
            TEST_FIREFOX='missing', TEST_FIREFOX_INSTALL_FAIL='1',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('SHOULD_NOT_INSTALL_THEME', result.stdout)

    def test_help_and_unknown_argument_have_no_side_effects(self):
        result = self.box.run(['--help'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Usage:', result.stdout)
        result = self.box.run(['--unknown'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unknown argument', result.stderr)
        self.assertEqual(self.box.log(), '')

    def test_session_actions_require_explicit_yes(self):
        cases = [
            ('Y\n', 'systemctl\treboot\n'),
            ('y\n', 'systemctl\treboot\n'),
            ('N\nY\n', 'qdbus6\torg.kde.Shutdown /Shutdown org.kde.Shutdown.logout\n'),
            ('n\ny\n', 'qdbus6\torg.kde.Shutdown /Shutdown org.kde.Shutdown.logout\n'),
            ('N\nN\n', ''), ('\n\n', ''), ('', ''),
            ('invalid\nn\n?\nY\n', 'qdbus6\torg.kde.Shutdown /Shutdown org.kde.Shutdown.logout\n'),
        ]
        for answers, expected in cases:
            with self.subTest(answers=answers):
                (self.box.root / 'commands.log').unlink(missing_ok=True)
                result = self.box.shell('finish_installation', answers)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.box.log(), expected)
                if answers.startswith('invalid'):
                    self.assertEqual(result.stdout.count('Please enter Y or N.'), 2)

    def test_unpack_with_and_without_wrapper_and_corrupt_archive(self):
        for name, member in [('wrapped', 'wrapped/content.txt'), ('flat', 'content.txt')]:
            with zipfile.ZipFile(self.box.sources / f'{name}.zip', 'w') as archive:
                archive.writestr(member, 'theme data')
            result = self.box.shell(
                'WORK="$TEST_ROOT/work"; SOURCES="$TEST_ROOT/project with spaces/sources"\n'
                f'dir=$(unpack {name})\ncat "$dir/content.txt"'
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'theme data')
        (self.box.sources / 'broken.zip').write_text('invalid ZIP')
        result = self.box.shell(
            'WORK="$TEST_ROOT/work"; SOURCES="$TEST_ROOT/project with spaces/sources"\n'
            'dir=$(unpack broken)\necho SHOULD_NOT_CONTINUE'
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('SHOULD_NOT_CONTINUE', result.stdout)

    def test_existing_non_repository_is_not_overwritten(self):
        dest = self.box.root / 'existing'
        dest.mkdir()
        (dest / 'keep').write_text('original')
        result = self.box.shell('clone_if_missing https://example.invalid/repo "$TEST_ROOT/existing"')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((dest / 'keep').read_text(), 'original')
        self.assertEqual(self.box.log(), '')

    def test_existing_repository_is_not_cloned_again(self):
        (self.box.root / 'existing/.git').mkdir(parents=True)
        result = self.box.shell('clone_if_missing https://example.invalid/repo "$TEST_ROOT/existing"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.box.log(), '')

    def test_plasma_restart_falls_back_when_user_service_is_unavailable(self):
        result = self.box.shell('restart_plasma; wait', TEST_FAIL_START='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('kstart\tplasmashell', self.box.log())

    def test_repeated_copy_preserves_unrelated_files(self):
        source = self.box.root / 'theme'
        source.mkdir()
        (source / 'new').write_text('new asset')
        dest = self.box.home / 'theme'
        dest.mkdir()
        (dest / 'custom').write_text('custom asset')
        result = self.box.shell(
            'BACKUP="$TEST_ROOT/backup"\n'
            'copy_user "$TEST_ROOT/theme" "$HOME/theme" theme\n'
            'copy_user "$TEST_ROOT/theme" "$HOME/theme" theme'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((dest / 'custom').read_text(), 'custom asset')
        self.assertEqual((dest / 'new').read_text(), 'new asset')


@unittest.skipIf(os.geteuid() == 0, 'Integration tests require a regular user, like the installer')
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)

    def test_complete_installation_with_real_archives_and_backups(self):
        result = self.box.run(answers='N\nN\n', TEST_FIREFOX='missing')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in (
            '.local/share/aurorae/themes/MacSequoia-Dark/metadata.json',
            '.themes/MacTahoe-Light/gtk-4.0/gtk.css',
            '.config/Kvantum/SumacDayMoltenGlass/SumacDayMoltenGlass.kvconfig',
            '.local/share/icons/WhiteSur-cursors/index.theme',
            '.local/share/plasma/plasmoids/CircleClock/metadata.json',
            '.local/share/fastfetch/presets/sysinfo.jsonc',
            '.config/cava/config', '.config/gtk-4.0/gtk.css', '.zshrc',
        ):
            self.assertTrue((self.box.home / path).exists(), path)
        layout = '.config/plasma-org.kde.plasma.desktop-appletsrc'
        with zipfile.ZipFile(PROJECT / 'sources/plasma6macos-kde-config.zip') as archive:
            expected = archive.read('plasma6macos-kde-config/conf-kubuntu/plasma-org.kde.plasma.desktop-appletsrc')
        self.assertEqual((self.box.home / layout).read_bytes(), expected)
        backups = list((self.box.home / '.local/state/kde-plasma-to-macos/backups').iterdir())
        self.assertEqual(len(backups), 1)
        backup = backups[0]
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual((backup / 'kde-config/kdeglobals').read_text(), 'OLD KDE SETTINGS\n')
        self.assertEqual((backup / 'zsh-konsole/.zshrc').read_text(), 'OLD ZSH SETTINGS\n')
        self.assertEqual((backup / 'dconf.ini').read_text(), '[test]\nvalue=true\n')
        self.assertEqual((self.box.root / 'sddm-theme.conf').read_text(), '[Theme]\nCurrent=tahoe-sddm\n')
        self.assertFalse(list(self.box.root.glob('tmp.*')), 'Temporary build files were not cleaned up')
        log = self.box.log()
        self.assertNotIn('systemctl\treboot', log)
        self.assertNotIn('qdbus6\t', log)
        self.assertIn('systemctl\t--user stop plasma-plasmashell.service', log)
        self.assertIn('systemctl\t--user start plasma-plasmashell.service', log)
        self.assertIn('flatpak\t--user install', log)
        system_copies = [line for line in log.splitlines() if line.startswith('sudo\trsync ')]
        self.assertEqual(len(system_copies), 3)
        self.assertTrue(all('--chown=root:root' in line for line in system_copies))
        self.assertLess(log.index('sudo\tapt-get install -y --no-remove firefox\n'),
                        log.index('https://github.com/linuxscoop/safarifox-theme.git'))

    def test_checksum_failure_stops_before_deb_install_and_session_actions(self):
        result = self.box.run(answers='Y\n', TEST_BAD_CHECKSUM='1')
        self.assertNotEqual(result.returncode, 0)
        deb_installs = [line for line in self.box.log().splitlines()
                        if line.startswith('sudo\tapt-get install') and line.endswith('.deb')]
        self.assertEqual(deb_installs, [])
        self.assertNotIn('cmake\t', self.box.log())
        self.assertNotIn('systemctl\treboot', self.box.log())
        self.assertNotIn('qdbus6\t', self.box.log())
        self.assertIn('Installation stopped.', result.stderr)
        self.assertFalse(list(self.box.root.glob('tmp.*')))

    def test_failed_configuration_copy_restarts_plasma(self):
        result = self.box.run(TEST_FAIL_CONFIG='1', TEST_FALLBACK='1')
        self.assertNotEqual(result.returncode, 0)
        log = self.box.log()
        self.assertIn('kquitapp6\tplasmashell', log)
        self.assertGreater(log.rfind('systemctl\t--user start plasma-plasmashell.service'),
                           log.rfind('kquitapp6\tplasmashell'))
        self.assertNotIn('systemctl\treboot', log)
        self.assertFalse(list(self.box.root.glob('tmp.*')))

    def test_unsupported_architecture_is_rejected_before_installation(self):
        result = self.box.run(TEST_ARCH='arm64')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('amd64 only', result.stderr)
        self.assertNotIn('sudo\t', self.box.log())

    def test_non_plasma_session_is_rejected_before_installation(self):
        result = self.box.run(XDG_CURRENT_DESKTOP='GNOME')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('KDE Plasma 6 session', result.stderr)
        self.assertNotIn('sudo\t', self.box.log())


if __name__ == '__main__':
    unittest.main()
