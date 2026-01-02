#!/bin/bash
set -e

# Sync UID/GID with host user (only run if we're root)
if [ "$(id -u)" = "0" ]; then
    if [ -n "$HOST_UID" ] && [ "$HOST_UID" != "1000" ]; then
        usermod -u "$HOST_UID" dev 2>/dev/null || true
    fi

    if [ -n "$HOST_GID" ] && [ "$HOST_GID" != "1000" ]; then
        groupmod -g "$HOST_GID" dev 2>/dev/null || true
    fi

    # Fix ownership of home directory if UID changed
    if [ -n "$HOST_UID" ] && [ "$HOST_UID" != "1000" ]; then
        chown -R dev:dev /home/dev 2>/dev/null || true
    fi
fi

# Switch to dev user and execute command
if [ "$(id -u)" = "0" ]; then
    exec gosu dev "$@"
else
    exec "$@"
fi
