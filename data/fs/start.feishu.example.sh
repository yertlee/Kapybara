#!/usr/bin/env bash

set -euo pipefail
set -a
if [ -f "$HOME/.env" ]; then
  # Windows editors may save .env as CRLF; strip only line-ending CR bytes.
  . <(sed 's/\r$//' "$HOME/.env")
fi
set +a

exec env K_CONFIG_BASE="${K_CONFIG_BASE:-/home/k/.kapybara}" \
  python -m kapy_collections.starters.feishu
