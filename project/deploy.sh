#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
chmod 600 .env
docker compose up -d --build
echo "Open http://$(hostname -I | awk '{print $1}'):${APP_PORT:-8080}"
