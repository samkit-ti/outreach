#!/usr/bin/env bash
# git-sync.sh — Daily sync of CRM, logs, and evolution rules to Git
# Also syncs each business repo's data directory
set -euo pipefail

HERMES_DIR="/opt/hermes-agent"
BUSINESS_DIR="/opt/business"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)

echo "=== Git Sync: Agent + Business Repos ==="

# --- Sync agent data (if agent dir is a git repo) ---
if [ -d "$HERMES_DIR/.git" ]; then
    cd "$HERMES_DIR"
    
    # Export CRM data
    mkdir -p data
    sqlite3 "$HERMES_DIR/crm.db" ".mode json" ".once $HERMES_DIR/data/crm_export.json" "SELECT * FROM leads;" 2>/dev/null || true
    sqlite3 "$HERMES_DIR/crm.db" ".mode json" ".once $HERMES_DIR/data/interactions_export.json" "SELECT * FROM interactions ORDER BY timestamp DESC LIMIT 500;" 2>/dev/null || true
    
    # Sync evolution rules
    cp "$HERMES_DIR/evolution_rules.json" "$HERMES_DIR/data/" 2>/dev/null || true
    
    # Sync usage logs
    cp "$HERMES_DIR/usage_log.json" "$HERMES_DIR/data/" 2>/dev/null || true
    
    # Commit and push agent data
    if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
        git add -A
        git commit -m "auto: agent sync $TIMESTAMP" || true
        git push || echo "Agent push failed — will retry tomorrow"
    fi
fi

# --- Sync each business repo ---
for repo in "$BUSINESS_DIR"/*; do
    if [ -d "$repo/.git" ]; then
        name=$(basename "$repo")
        echo "Syncing business repo: $name"
        cd "$repo"
        
        # Each business repo can have its own data/ dir
        mkdir -p data
        
        # Copy relevant market intel, reports, etc.
        # Business-specific CRM exports could go here too
        
        if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
            git add -A
            git commit -m "auto: business sync $TIMESTAMP" || true
            git push || echo "$name push failed — will retry tomorrow"
        fi
    fi
done

echo "=== Sync Complete ==="
