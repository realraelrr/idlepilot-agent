#!/usr/bin/env bash
set -euo pipefail

mkdir -p /browser-profile /browser-state

exec chromium \
  --user-data-dir=/browser-profile \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --no-first-run \
  --no-default-browser-check \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --display=:99
