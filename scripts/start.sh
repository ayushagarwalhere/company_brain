#!/bin/sh
# Container entrypoint: FalkorDB in the background (in-memory, no persistence), then the app.
set -e
redis-server --loadmodule "$FALKORDB_BIN_PATH/falkordb.so" \
  --bind 127.0.0.1 --port 6379 --save "" --appendonly no --daemonize yes
exec python -m scripts.serve
