#!/usr/bin/env bash
# deploy.sh — Deploy latest agent code and restart services
set -euo pipefail

HERMES_DIR="/opt/hermes-agent"
BUSINESS_DIR="/opt/business"
HERMES_USER="hermes"

echo "=== Deploying latest Hermes Agent ==="

# Pull latest agent code (from assistant repo)
# Assumes /opt/hermes-agent is a git clone of assistant repo
echo "[1/5] Pulling latest agent code..."
if [ -d "$HERMES_DIR/.git" ]; then
    sudo -u "$HERMES_USER" bash -c "cd $HERMES_DIR && git pull"
else
    echo "Warning: $HERMES_DIR is not a git repo. Skipping agent code update."
fi

# Pull latest business repos
echo "[2/5] Pulling latest business repos..."
for repo in "$BUSINESS_DIR"/*; do
    if [ -d "$repo/.git" ]; then
        echo "  Updating $(basename $repo)..."
        sudo -u "$HERMES_USER" bash -c "cd $repo && git pull" || true
    fi
done

# Re-sync skills
echo "[3/5] Syncing skills..."
rsync -av --delete "$HERMES_DIR/skills/" "$HERMES_DIR/active-skills/"
chown -R "$HERMES_USER:$HERMES_USER" "$HERMES_DIR/active-skills"

# Re-sync formulas
echo "[4/5] Syncing beads formulas..."
rsync -av --delete "$HERMES_DIR/beads/formulas/" "$HERMES_DIR/.beads/formulas/"
chown -R "$HERMES_USER:$HERMES_USER" "$HERMES_DIR/.beads/formulas"

# Restart service
echo "[5/5] Restarting hermes-gateway..."
systemctl restart hermes-gateway
sleep 2
systemctl status hermes-gateway --no-pager

echo ""
echo "=== Deploy Complete ==="
