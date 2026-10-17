#!/bin/sh
# Container entrypoint: FalkorDB in the background (in-memory, no persistence), the chat bots when their tokens are
# set, then the app.
set -e
redis-server --loadmodule "$FALKORDB_BIN_PATH/falkordb.so" \
  --bind 127.0.0.1 --port 6379 --save "" --appendonly no --daemonize yes

# The Slack (Socket Mode) and Discord bots run beside the API when configured. Each waits until the API answers (the
# graph is built by then) and restarts if it exits; a bot that keeps failing never takes the website down.
bot() {
  until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT:-8000}/api/health')" 2>/dev/null; do sleep 3; done
  while true; do python -m "$1" || true; sleep 10; done
}
if [ -n "$SLACK_APP_TOKEN" ]; then bot bots.slack_bot & fi
if [ -n "$DISCORD_BOT_TOKEN" ]; then bot bots.discord_bot & fi

exec python -m scripts.serve
