#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Hermes Container Init Script
# =============================================================================
# Problem: SQLite databases don't work reliably on Azure Files (SMB) because
#   of file locking issues.
# Solution:
#   - HERMES_HOME is on local ephemeral storage (/app/.hermes) for SQLite
#   - Azure Files is mounted at /app/persistent for config backup
#   - This script restores config on startup and backs up on shutdown
# =============================================================================

PERSISTENT_DIR="/app/persistent/.hermes"
HERMES_HOME="${HERMES_HOME:-/app/.hermes}"

log() {
    echo "[init-hermes] $*" >&2
}

# -----------------------------------------------------------------------------
# RESTORE: Copy persistent config into HERMES_HOME on startup
# -----------------------------------------------------------------------------
restore_from_persistent() {
    if [[ ! -d "$PERSISTENT_DIR" ]]; then
        log "No persistent data found at $PERSISTENT_DIR (first run or empty share)"
        return
    fi

    log "Restoring persistent data from $PERSISTENT_DIR ..."

    # Create HERMES_HOME dirs
    mkdir -p "$HERMES_HOME"

    # Copy non-DB files that are safe to persist on Azure Files
    for item in .env skills cron active-skills; do
        src="$PERSISTENT_DIR/$item"
        dst="$HERMES_HOME/$item"
        if [[ -e "$src" ]]; then
            # Use rsync-like behavior: copy if newer or doesn't exist
            if [[ ! -e "$dst" || "$src" -nt "$dst" ]]; then
                rm -rf "$dst"
                cp -r "$src" "$dst"
                log "  Restored $item"
            fi
        fi
    done

    log "Restore complete"
}

# -----------------------------------------------------------------------------
# BACKUP: Copy config back to persistent storage
# -----------------------------------------------------------------------------
backup_to_persistent() {
    log "Backing up data to $PERSISTENT_DIR ..."
    mkdir -p "$PERSISTENT_DIR"

    # Backup non-DB files only (SQLite DBs stay local)
    for item in .env skills cron active-skills; do
        src="$HERMES_HOME/$item"
        dst="$PERSISTENT_DIR/$item"
        if [[ -e "$src" ]]; then
            rm -rf "$dst"
            cp -r "$src" "$dst"
            log "  Backed up $item"
        fi
    done

    log "Backup complete"
}

# -----------------------------------------------------------------------------
# PERIODIC BACKUP: Run backup every N seconds in background
# -----------------------------------------------------------------------------
start_periodic_backup() {
    local interval="${BACKUP_INTERVAL:-300}"  # default 5 minutes
    log "Starting periodic backup every ${interval}s ..."
    while true; do
        sleep "$interval"
        backup_to_persistent
    done &
}

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
main() {
    log "=========================================="
    log "Hermes Container Init"
    log "HERMES_HOME=$HERMES_HOME"
    log "PERSISTENT_DIR=$PERSISTENT_DIR"
    log "=========================================="

    # Restore config on startup
    restore_from_persistent

    # Create HERMES_HOME structure if it doesn't exist
    mkdir -p "$HERMES_HOME"/{skills,active-skills,cron,logs}

    # Start background periodic backup
    start_periodic_backup

    # Set up trap to backup on shutdown signals
    trap backup_to_persistent EXIT SIGTERM SIGINT

    log "Starting hermes gateway ..."
    exec hermes gateway "$@"
}

main "$@"
