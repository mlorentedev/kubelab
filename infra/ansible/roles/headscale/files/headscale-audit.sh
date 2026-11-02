#!/bin/sh
# Forced command for the Headscale host's audit identity (SEC-037, #2734).
#
# sshd runs this for every connection made with a key authorized as
# `restrict,command="/usr/local/bin/headscale-audit"` and passes the client's
# request in SSH_ORIGINAL_COMMAND. Each allowed request is a fixed read-only
# string matched whole: no globs, no arguments, no shell, so a chain, pipe or
# substitution can never match. Anything else exits 126. Every attempt is logged
# under the tag `headscale-audit` (`journalctl -t headscale-audit`).
#
# The role installs this root:root 0755, so the account it runs as cannot edit
# its own allowlist. Never add a write subcommand here.
set -u

request="${SSH_ORIGINAL_COMMAND-}"
client="${SSH_CLIENT:-unknown}"
client="${client%% *}"

record() {
    # Control bytes become `?`, so a request cannot forge extra log lines.
    shown=$(printf '%s' "$request" | tr '\001-\037\177' '?')
    logger -t headscale-audit -- "$1 from=$client command=$shown" 2>/dev/null || :
}

case "$request" in
    '')
        record allowed
        exit 0
        ;;
    'true')
        record allowed
        exit 0
        ;;
    'hostname')
        record allowed
        exec hostname
        ;;
    'id')
        record allowed
        exec id
        ;;
    'uname -a')
        record allowed
        exec uname -a
        ;;
    'uptime')
        record allowed
        exec uptime
        ;;
    'docker exec headscale headscale nodes list -o json')
        record allowed
        exec docker exec headscale headscale nodes list -o json
        ;;
    'docker exec headscale headscale users list -o json')
        record allowed
        exec docker exec headscale headscale users list -o json
        ;;
    'docker exec headscale headscale policy get')
        record allowed
        exec docker exec headscale headscale policy get
        ;;
    'docker exec headscale headscale version')
        record allowed
        exec docker exec headscale headscale version
        ;;
    *)
        record refused
        echo "headscale-audit: command not allowed" >&2
        exit 126
        ;;
esac
