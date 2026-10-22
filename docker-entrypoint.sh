#!/bin/sh
set -eu

# Empty named volumes inherit the image directory ownership. Repair only the
# top-level paths so an existing volume from an older image also remains usable.
for directory in /app/data /app/logs /app/cache /app/papers; do
    mkdir -p "$directory"
    chown radar:radar "$directory"
done

exec gosu radar "$@"
