#!/usr/bin/env bash
# Launch cURLsender detached from the calling terminal.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
nohup python3 "$DIR/curlsender.py" >/dev/null 2>&1 &
disown
