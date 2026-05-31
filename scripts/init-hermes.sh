#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Hermes Container Init Script (EmptyDir edition)
# =============================================================================
# Architecture:
#   - EmptyDir volume mounted at /app/.hermes (HERMES_HOME)
#     -> SQLite databases survive container restarts / crashes
#     -> Local filesystem: no SMB locking issues
#     -> Lost ONLY when the replica is replaced (node failure, revision update)
#   - Azure Files mounted at /app/backup
#     -> Cross-replica disaster recovery for config/skills/cron
#     -> NEVER used for SQLite files (SMB lacks POSIX advisory locking)
#
# Thread isolation:
#   - Hermes_state uses session_id + user_id columns for conversation isolation
#   - SQLite connection uses check_same_thread=False + Python threading.Lock()
#   - Each outreach thread maps to a unique session_id, preventing leakage
# =============================================================================

BACKUP_DIR="${BACKUP_DIR:-/app/backup/.hermes}"
HERMES_HOME="${HERMES_HOME:-/app/.hermes}"
DATA_DIR="${HERMES_DIR:-/app/data}"

log() {
    echo "[init-hermes] $*" >&2
}

# ---------------------------------------------------------------------------
# INIT CRM DATABASE: Create tables if they don't exist
# ---------------------------------------------------------------------------
init_crm_database() {
    log "Initializing CRM database ..."
    python3 /app/scripts/init-crm-db.py
    log "CRM database ready"
}

# ---------------------------------------------------------------------------
# is_emptydir_populated: check if HERMES_HOME already has data
# ---------------------------------------------------------------------------
is_emptydir_populated() {
    # If sessions.db exists, this is a restart (EmptyDir survived)
    [[ -f "$HERMES_HOME/sessions.db" ]]
}

# ---------------------------------------------------------------------------
# RESTORE: Copy backup into HERMES_HOME only on fresh replica startup
# ---------------------------------------------------------------------------
restore_from_backup() {
    if is_emptydir_populated; then
        log "EmptyDir already has sessions.db — skipping restore (preserving thread continuity)"
        return
    fi

    if [[ ! -d "$BACKUP_DIR" ]]; then
        log "No backup data found at $BACKUP_DIR (first run or empty share)"
        return
    fi

    log "Restoring backup from $BACKUP_DIR to $HERMES_HOME ..."
    mkdir -p "$HERMES_HOME"

    # Restore non-DB files that are safe on Azure Files
    for item in .env skills cron active-skills; do
        src="$BACKUP_DIR/$item"
        dst="$HERMES_HOME/$item"
        if [[ -e "$src" ]]; then
            rm -rf "$dst"
            cp -r "$src" "$dst"
            log "  Restored $item"
        fi
    done

    log "Restore complete"
}

# ---------------------------------------------------------------------------
# BACKUP: Copy config back to Azure Files (NOT SQLite DBs)
# ---------------------------------------------------------------------------
backup_to_azure_files() {
    log "Backing up config to $BACKUP_DIR ..."
    mkdir -p "$BACKUP_DIR"

    # Config / stateless files only — SQLite DBs stay on EmptyDir
    for item in .env skills cron active-skills; do
        src="$HERMES_HOME/$item"
        dst="$BACKUP_DIR/$item"
        if [[ -e "$src" ]]; then
            rm -rf "$dst"
            cp -r "$src" "$dst"
            log "  Backed up $item"
        fi
    done

    log "Backup complete"
}

# ---------------------------------------------------------------------------
# PERIODIC BACKUP: Run backup every N seconds in background
# ---------------------------------------------------------------------------
start_periodic_backup() {
    local interval="${BACKUP_INTERVAL:-300}"  # default 5 minutes
    log "Starting periodic backup every ${interval}s ..."
    while true; do
        sleep "$interval"
        backup_to_azure_files
    done &
}

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
main() {
    log "=========================================="
    log "Hermes Container Init (EmptyDir edition)"
    log "HERMES_HOME=$HERMES_HOME"
    log "DATA_DIR=$DATA_DIR"
    log "BACKUP_DIR=$BACKUP_DIR"
    log "=========================================="

    # Initialize CRM database first
    init_crm_database

    # On restart: EmptyDir retains data; on fresh replica: restore from backup
    restore_from_backup

    # Ensure directory structure exists
    mkdir -p "$HERMES_HOME"/{skills,active-skills,cron,logs}
    mkdir -p "$DATA_DIR"

    # Start background periodic backup
    start_periodic_backup

    # Backup on any shutdown signal
    trap backup_to_azure_files EXIT SIGTERM SIGINT

    log "Starting hermes gateway ..."
    exec hermes gateway "$@"
}

main "$@"
