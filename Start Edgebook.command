#!/bin/bash
# Double-click to start Edgebook. Close this window (or press Ctrl+C) to stop it.
cd "$(dirname "$0")"
exec python3 -m edgebook
