#!/usr/bin/env python3
"""Record and restore installer-owned paths without executing backup contents."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys

VERSION = 1
SYSTEM_ROOTS = ('/usr', '/etc/apt', '/etc/sddm.conf.d',
                '/etc/X11/default-display-manager', '/etc/systemd/system/display-manager.service')


def within(path, root):
    return path == root or root in path.parents


def clone_tree(source, target):
    shutil.copytree(source, target, symlinks=True)
    if os.geteuid() == 0:
        for path in [Path(source), *Path(source).rglob('*')]:
            info = path.lstat()
            dest = Path(target) / path.relative_to(source)
            os.chown(dest, info.st_uid, info.st_gid, follow_symlinks=False)


class Journal:
    def __init__(self, directory, home, scope=None):
        self.directory = Path(directory).absolute()
        self.home = Path(home).absolute()
        self.path = self.directory / 'manifest.json'
        if scope:
            if self.path.exists():
                raise ValueError('A journal already exists at this path')
            self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            self.data = {'version': VERSION, 'home': str(self.home), 'scope': scope, 'entries': []}
            self.save()
        else:
            self.data = json.loads(self.path.read_text())
            if self.data['version'] != VERSION or self.data['home'] != str(self.home):
                raise ValueError('Unsupported journal version or a different HOME directory')
        self.index = {entry['path']: entry for entry in self.data['entries']}
        if self.data['scope'] not in ('user', 'system'):
            raise ValueError('Invalid journal scope')

    def save(self):
        tmp = self.directory / 'manifest.tmp'
        tmp.write_text(json.dumps(self.data, indent=2) + '\n')
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def validate(self, target):
        target = Path(os.path.abspath(target))
        roots = [self.home] if self.data['scope'] == 'user' else [Path(p) for p in SYSTEM_ROOTS]
        if not any(within(target, root) for root in roots) or target == self.home:
            raise ValueError(f'Path is outside the allowed restore locations: {target}')
        # A symlink at the target itself is restored as a symlink, never followed.
        parent = target.parent.resolve()
        if not any(within(parent, root.resolve()) for root in roots):
            # Exact file roots (e.g. the display-manager link) have a parent outside the root.
            if target not in roots or target.parent.is_symlink():
                raise ValueError(f'Parent symlink escapes the restore location: {target}')
        return target

    def capture(self, target, directory_metadata=False, save=True):
        target = self.validate(target)
        if str(target) in self.index:
            return
        for parent in target.parents:
            old = self.index.get(str(parent))
            if old and old['kind'] in ('absent', 'tree'):
                return
        if not os.path.lexists(target):
            # Record the first missing parent as well, so empty directories do not remain.
            while not target.parent.exists() and target.parent != self.home:
                try:
                    self.validate(target.parent)
                except ValueError:
                    break
                target = target.parent
            if str(target) in self.index:
                return
        entry = {'path': str(target)}
        if not os.path.lexists(target):
            entry['kind'] = 'absent'
        else:
            info = target.lstat()
            entry.update(mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid,
                         atime=info.st_atime_ns, mtime=info.st_mtime_ns)
            if target.is_symlink():
                entry.update(kind='symlink', link=os.readlink(target))
            elif target.is_dir() and directory_metadata:
                entry['kind'] = 'directory'
            elif target.is_file() or target.is_dir():
                entry['kind'] = 'tree' if target.is_dir() else 'file'
                entry['snapshot'] = str(len(self.data['entries']))
                snapshot = self.directory / entry['snapshot']
                if target.is_dir():
                    clone_tree(target, snapshot)
                else:
                    shutil.copy2(target, snapshot, follow_symlinks=False)
            else:
                raise ValueError(f'Refusing to back up a special file: {target}')
        self.data['entries'].append(entry)
        self.index[str(target)] = entry
        if save:
            self.save()

    def capture_copy(self, source, target):
        self._capture_copy(source, target)
        self.save()

    def _capture_copy(self, source, target):
        source, target = Path(source), Path(target)
        if not os.path.lexists(source):
            raise ValueError(f"Copy source does not exist: {source}")
        if source.is_dir() and not source.is_symlink():
            if target.absolute() != self.home:
                self.capture(target, directory_metadata=True, save=False)
            if target.is_dir() and not target.is_symlink():
                for child in source.iterdir():
                    self._capture_copy(child, target / child.name)
        else:
            self.capture(target, save=False)

    def verify(self):
        protected = {Path(p) for p in ('/usr', '/usr/bin', '/usr/lib', '/usr/lib64', '/usr/share',
                                      '/usr/local', '/usr/local/bin', '/usr/local/share')}
        for entry in self.data['entries']:
            target = self.validate(entry['path'])
            if within(self.directory, target) and entry['kind'] != 'directory':
                raise ValueError(f'Restore target contains its own backup: {target}')
            if target in protected and entry['kind'] != 'directory':
                raise ValueError(f'Refusing a destructive restore of a system root: {target}')
            if entry['kind'] != 'absent':
                for key in ('mode', 'uid', 'gid', 'atime', 'mtime'):
                    if not isinstance(entry.get(key), int):
                        raise ValueError(f'Missing or invalid metadata for {target}')
            if entry['kind'] not in ('absent', 'directory', 'file', 'tree', 'symlink'):
                raise ValueError('Unknown journal entry type')
            if entry['kind'] in ('file', 'tree'):
                snapshot = entry['snapshot']
                if not snapshot.isdecimal() or not (self.directory / snapshot).exists():
                    raise ValueError(f'Missing backup for {entry["path"]}')

    @staticmethod
    def remove(path):
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        elif os.path.lexists(path):
            raise ValueError(f'Refusing to remove a special file: {path}')

    def save_current(self, recovery):
        self.verify()
        if (Path(recovery) / 'manifest.json').exists():
            saved = Journal(recovery, self.home)
        else:
            saved = Journal(recovery, self.home, self.data['scope'])
        for entry in self.data['entries']:
            saved.capture(entry['path'], directory_metadata=entry['kind'] == 'directory', save=False)
        saved.save()

    def restore(self, apply=False, recovery=None):
        self.verify()
        if not apply:
            from collections import Counter
            counts = Counter(entry["kind"] for entry in self.data["entries"])
            print(f'Journal {self.directory}: {len(self.data["entries"])} paths ({dict(counts)})')
            return
        if not recovery:
            raise ValueError('A recovery journal is required before restoring files')
        self.save_current(recovery)
        for entry in reversed(self.data['entries']):
            target = self.validate(entry['path'])
            if entry['kind'] == 'directory':
                if not target.is_dir() or target.is_symlink():
                    self.remove(target)
                    target.mkdir(parents=True)
            else:
                self.remove(target)
                if entry['kind'] == 'absent':
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if entry['kind'] == 'symlink':
                    target.symlink_to(entry['link'])
                elif entry['kind'] == 'tree':
                    clone_tree(self.directory / entry['snapshot'], target)
                else:
                    shutil.copy2(self.directory / entry['snapshot'], target)
            if os.geteuid() == 0:
                os.chown(target, entry['uid'], entry['gid'], follow_symlinks=False)
            if not target.is_symlink():
                target.chmod(entry['mode'])
                os.utime(target, ns=(entry['atime'], entry['mtime']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('journal')
    parser.add_argument('home')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init').add_argument('scope', choices=['user', 'system'])
    sub.add_parser('path').add_argument('target')
    copy = sub.add_parser('copy')
    copy.add_argument('source')
    copy.add_argument('target')
    sub.add_parser('save-current').add_argument('recovery')
    restore = sub.add_parser('restore')
    restore.add_argument('--apply', action='store_true')
    restore.add_argument('--recovery')
    args = parser.parse_args()
    journal = Journal(args.journal, args.home, args.scope if args.command == 'init' else None)
    if args.command == 'path':
        journal.capture(args.target)
    elif args.command == 'copy':
        journal.capture_copy(args.source, args.target)
    elif args.command == 'save-current':
        journal.save_current(args.recovery)
    elif args.command == 'restore':
        journal.restore(args.apply, args.recovery)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print(f'File state error: {error}', file=sys.stderr)
        sys.exit(1)
