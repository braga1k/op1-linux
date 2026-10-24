#!/usr/bin/env sh
set -eu
op1_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$op1_directory/packaging/install.py" "$@"
