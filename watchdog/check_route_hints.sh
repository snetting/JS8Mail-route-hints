#!/usr/bin/env bash
set -u

# Recover the route-hints container if it exits or its health endpoint fails.
# Docker's unless-stopped policy handles process crashes and host reboots; this
# check also covers an application that is alive but no longer serving healthz.

container_name="${ROUTE_HINTS_CONTAINER:-js8mail-route-hints}"
health_url="${ROUTE_HINTS_HEALTH_URL:-http://127.0.0.1:${ROUTE_HINTS_PORT:-8787}/healthz}"
cooldown_seconds="${ROUTE_HINTS_RESTART_COOLDOWN:-600}"
state_dir="/run/route-hints-watchdog"
state_file="$state_dir/last-restart"
log_file="/var/log/route-hints-watchdog.log"

mkdir -p "$state_dir"
exec 9>"$state_dir/lock"
if ! flock -n 9; then
  exit 0
fi

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*" >> "$log_file"
}

if ! /usr/bin/docker inspect "$container_name" >/dev/null 2>&1; then
  log "container $container_name does not exist; nothing to recover"
  exit 0
fi

status=$(/usr/bin/docker inspect --format '{{.State.Status}}' "$container_name" 2>/dev/null || true)
health=$(/usr/bin/docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_name" 2>/dev/null || true)
failure_reason=""

if [[ "$status" != "running" ]]; then
  failure_reason="container status is $status"
elif [[ "$health" == "starting" ]]; then
  # Allow the application its healthcheck grace period after a restart.
  exit 0
elif [[ "$health" == "unhealthy" ]]; then
  failure_reason="Docker healthcheck is unhealthy"
elif ! /usr/bin/curl --fail --silent --show-error --max-time 5 "$health_url" >/dev/null 2>&1; then
  failure_reason="health endpoint check failed"
fi

[[ -z "$failure_reason" ]] && exit 0

now=$(date +%s)
last=0
if [[ -r "$state_file" ]]; then
  read -r last < "$state_file" || last=0
fi
if [[ "$last" =~ ^[0-9]+$ ]] && (( now - last < cooldown_seconds )); then
  log "$failure_reason; restart suppressed (cooldown ${cooldown_seconds}s)"
  exit 0
fi

printf '%s\n' "$now" > "$state_file"
if [[ "$status" == "running" ]]; then
  action="restart"
  /usr/bin/docker restart "$container_name" >/dev/null 2>&1
else
  action="start"
  /usr/bin/docker start "$container_name" >/dev/null 2>&1
fi

if [[ $? -eq 0 ]]; then
  log "$failure_reason; container $action requested"
else
  log "$failure_reason; container $action failed"
fi
