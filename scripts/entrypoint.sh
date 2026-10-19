#!/bin/bash
set -euo pipefail
umask 077

case "${1:-start}" in
    start)
        exec python3 -u /opt/renegade-x/runtime.py
        ;;
    install)
        exec python3 -u /opt/renegade-x/install.py --root "${2:-/home/container}"
        ;;
    *)
        exec "$@"
        ;;
esac
