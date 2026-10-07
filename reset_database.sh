#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "This removes the PostgreSQL volume and all imported records, but keeps source code and .env."
read -r -p "Type RESET to continue: " confirm
if [[ "$confirm" != "RESET" ]]; then
  echo "Cancelled."
  exit 1
fi
docker compose down -v
docker compose up -d --build
echo "Fresh database started. Upload/import reports again."
