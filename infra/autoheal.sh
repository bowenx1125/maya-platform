#!/bin/sh
# Restart Maya containers that stay unhealthy.
#
# Docker's restart policy reacts only when a process exits; a backend that
# hangs keeps running and is merely marked "unhealthy" by its healthcheck
# (/health/ready, 6 failures 10 s apart). This loop restarts such a container
# once it has been unhealthy for AUTOHEAL_CONFIRM_CHECKS checks in a row, at
# most once per AUTOHEAL_COOLDOWN_SECONDS, and only containers carrying the
# opt-in label. AUTOHEAL_DRY_RUN=true logs what it would do instead.
set -u

LABEL="${AUTOHEAL_LABEL:-com.maya.autoheal=true}"
INTERVAL="${AUTOHEAL_INTERVAL_SECONDS:-20}"
CONFIRM="${AUTOHEAL_CONFIRM_CHECKS:-3}"
COOLDOWN="${AUTOHEAL_COOLDOWN_SECONDS:-300}"
STOP_TIMEOUT="${AUTOHEAL_STOP_TIMEOUT_SECONDS:-30}"
DRY_RUN="${AUTOHEAL_DRY_RUN:-false}"
MAX_LOOPS="${AUTOHEAL_MAX_LOOPS:-0}" # tests only; 0 runs forever
STATE="${AUTOHEAL_STATE_DIR:-/tmp/autoheal}"

mkdir -p "$STATE"

log() {
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) autoheal $*"
}

log "watching label=$LABEL interval=${INTERVAL}s confirm=$CONFIRM cooldown=${COOLDOWN}s dry_run=$DRY_RUN"
loops=0
while :; do
  now=$(date +%s)
  if unhealthy=$(docker ps -q --filter "label=$LABEL" --filter health=unhealthy); then
    unhealthy=$(echo "$unhealthy" | tr '\n' ' ')
    # A container that recovered (or went away) starts counting from zero.
    for file in "$STATE"/*.count; do
      [ -e "$file" ] || continue
      id=$(basename "$file" .count)
      case " $unhealthy " in
        *" $id "*) ;;
        *) rm -f "$file" ;;
      esac
    done
    for id in $unhealthy; do
      checks=$(($(cat "$STATE/$id.count" 2>/dev/null || echo 0) + 1))
      echo "$checks" >"$STATE/$id.count"
      name=$(docker inspect -f '{{.Name}}' "$id" 2>/dev/null | sed 's#^/##')
      if [ "$checks" -lt "$CONFIRM" ]; then
        log "unhealthy name=$name check=$checks/$CONFIRM"
        continue
      fi
      last=$(cat "$STATE/$id.restarted" 2>/dev/null || echo 0)
      if [ $((now - last)) -lt "$COOLDOWN" ]; then
        log "unhealthy name=$name restart skipped: restarted $((now - last))s ago"
        continue
      fi
      if [ "$DRY_RUN" = "true" ]; then
        log "dry-run would restart name=$name after $checks unhealthy checks"
        echo "$now" >"$STATE/$id.restarted"
        continue
      fi
      log "restarting name=$name after $checks unhealthy checks"
      if docker restart -t "$STOP_TIMEOUT" "$id" >/dev/null; then
        echo "$now" >"$STATE/$id.restarted"
        rm -f "$STATE/$id.count"
        log "restarted name=$name"
      else
        log "restart failed name=$name"
      fi
    done
  else
    log "docker ps failed; retrying"
  fi
  loops=$((loops + 1))
  if [ "$MAX_LOOPS" -gt 0 ] && [ "$loops" -ge "$MAX_LOOPS" ]; then
    exit 0
  fi
  sleep "$INTERVAL"
done
