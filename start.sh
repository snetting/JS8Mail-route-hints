#!/usr/bin/env sh
set -eu

port="${ROUTE_HINTS_PORT:-8787}"
data="${ROUTE_HINTS_DATA:-$(pwd)/data}"
name="${ROUTE_HINTS_CONTAINER:-js8mail-route-hints}"

mkdir -p "$data"

if command -v podman >/dev/null 2>&1; then
  runtime=podman
elif command -v docker >/dev/null 2>&1; then
  runtime=docker
else
  echo "Install Podman or Docker, then run this script again." >&2
  exit 1
fi

"$runtime" build -t js8mail-route-hints .
"$runtime" rm -f "$name" >/dev/null 2>&1 || true
exec "$runtime" run --name "$name" --restart unless-stopped \
  -p "${port}:${port}" \
  -e ROUTE_HINTS_HOST=0.0.0.0 \
  -e ROUTE_HINTS_PORT="$port" \
  -e ROUTE_HINTS_DATABASE=/data/route-hints.sqlite3 \
  -v "$(cd "$data" && pwd):/data" \
  js8mail-route-hints
