#!/usr/bin/env python3
"""Discover registered Firefox profiles and adapt a temporary SafariFox installer."""
import argparse
import configparser
from pathlib import Path
import re
import sys


def profiles(roots):
    home = Path.home().resolve()
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        ini = root / 'profiles.ini'
        if ini.is_file():
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(ini.read_text())
            for name in config.sections():
                if not name.startswith('Profile') or not config[name].get('Path'):
                    continue
                path = Path(config[name]['Path'])
                if config[name].get('IsRelative', '1') == '1':
                    path = root / path
                if path.is_dir():
                    found.append(path.resolve())
        found.extend(path.resolve() for path in root.iterdir() if path.is_dir()
                     and any(token in path.name for token in ('.default', '.dev-edition', '.esr')))
    unique = list(dict.fromkeys(found))
    for path in unique:
        if not path.is_relative_to(home) or any(char in str(path) for char in ('\n', '\r')):
            raise ValueError(f'Profile is outside the supported HOME backup scope: {path}')
    return unique


def prepare(script):
    text = script.read_text()
    # Keep the desktop user's HOME, rather than guessing from logname/SUDO_USER.
    text, count = re.subn(
        r'# --- Detect user environment ---.*?(?=# --- Firefox directories ---)',
        '# --- Detect user environment ---\nMY_HOME="${HOME:?HOME must be set}"\n\n',
        text, count=1, flags=re.DOTALL)
    if count != 1:
        raise ValueError('Unrecognized SafariFox user-home detection; refusing to run it')
    text, count = re.subn(
        r'^get_profiles\(\) \{\n.*?^\}',
        lambda _: 'get_profiles() {\n    local profiles\n'
        '    profiles=$(python3 "$SAFARIFOX_PROFILE_HELPER" list "$1") || return 1\n'
        '    [[ -n $profiles ]] || return 1\n    echo "$profiles"\n}',
        text, count=1, flags=re.DOTALL | re.MULTILINE)
    if count != 1:
        raise ValueError('Unrecognized SafariFox profile finder; refusing to run it')
    # Under set -e, ((installed++)) exits with status 1 when the old value was zero.
    text = re.sub(r'\(\(\s*installed\+\+\s*\)\)', '((installed+=1))', text)
    # Do not let upstream redetect the browser using snap/flatpak list | grep -q.
    # Under pipefail those pipelines can report false negatives after an early reader exit.
    if 'install_to_profile() {' not in text:
        raise ValueError('Unrecognized SafariFox profile installer; refusing to run it')
    runner = r'''# --- Run with the explicit profile list backed up by the parent installer ---
[[ -n ${SAFARIFOX_PROFILE_LIST:-} && -f $SAFARIFOX_PROFILE_LIST ]] || {
    echo 'SafariFox requires an explicit, backed-up profile list.' >&2
    exit 1
}
installed_profiles=0
while IFS= read -r profile || [[ -n $profile ]]; do
    [[ -n $profile && -d $profile ]] || {
        echo "SafariFox profile no longer exists: $profile" >&2
        exit 1
    }
    echo "Applying SafariFox to: $profile"
    install_to_profile "$profile"
    ((installed_profiles+=1))
done < "$SAFARIFOX_PROFILE_LIST"
(( installed_profiles > 0 )) || {
    echo 'SafariFox received an empty profile list.' >&2
    exit 1
}
echo "SafariFox installed to $installed_profiles profile(s)."
'''
    text, count = re.subn(r'^# --- Run main ---\s*\nmain\s*\Z',
                          lambda _: runner, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError('Unrecognized SafariFox entry point; refusing to run it')
    script.write_text(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list').add_argument('roots', nargs='+', type=Path)
    sub.add_parser('prepare-installer').add_argument('script', type=Path)
    args = parser.parse_args()
    if args.command == 'list':
        for profile in profiles(args.roots):
            print(profile)
    else:
        prepare(args.script)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, configparser.Error) as error:
        print(f'Firefox profile error: {error}', file=sys.stderr)
        sys.exit(1)
