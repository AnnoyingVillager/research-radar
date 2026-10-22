#!/bin/sh
set -eu

umask 077

# Empty named volumes inherit the image directory ownership. Repair only the
# top-level paths so an existing volume from an older image also remains usable.
for directory in /app/data /app/logs /app/cache /app/papers /app/secrets; do
    mkdir -p "$directory"
    chown radar:radar "$directory"
done

chown -R radar:radar /app/secrets
chmod 700 /app/secrets

exec gosu radar "$@"
