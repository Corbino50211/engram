#!/usr/bin/env bash
# Start engram.py with a real Python 3.8+. On Windows "python3" is often a Microsoft Store stub that only opens the Store.
for py in python3 python py; do
  if "$py" -c "import sys; sys.exit(sys.version_info < (3, 8))" 2>/dev/null; then
    exec "$py" "$(dirname "$0")/engram.py" "$@"
  fi
done
echo "engram: no Python 3.8+ found on PATH" >&2
