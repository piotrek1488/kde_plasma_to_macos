#!/usr/bin/env bash
set -Eeuo pipefail
if (( EUID == 0 )); then
    echo 'Run the test suite as a regular user so integration tests are not skipped.' >&2
    exit 1
fi
PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$PROJECT_DIR"
for script in install.sh uninstall.sh scripts/*.sh tests/*.sh; do
    bash -n "$script"
done
shellcheck -x install.sh uninstall.sh scripts/*.sh tests/*.sh
python3 -B -m unittest discover -s "$PROJECT_DIR/tests" -p 'test_*.py' -v
