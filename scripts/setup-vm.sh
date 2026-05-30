#!/usr/bin/env bash
# setup-vm.sh — One-shot VM provisioning script for PS3Labs Hermes Agent
# Run this on a fresh Ubuntu 24.04 VM with sudo access

set -euo pipefail

HERMES_DIR="/opt/hermes-agent"
BUSINESS_DIR="/opt/business"
HERMES_USER="hermes"
BUSINESS_REPO_URL="https://github.com/samkit-shah/ps3_labs_ai.git"

echo "=== Hermes Agent Multi-Business Setup ==="
echo "This script will install the Hermes agent infrastructure"
echo "and clone business repos into their own directories."
echo ""

# --- 1. System updates ---
echo "[1/12] Updating system packages..."
apt-get update -y
apt-get upgrade -y
apt-get install -y \
    curl wget git \
    python3 python3-pip python3-venv \
    nodejs npm \
    sqlite3 \
    encfs gocryptfs \
    build-essential \
    libffi-dev

# --- 2. Create user ---
echo "[2/12] Creating hermes user..."
if ! id "$HERMES_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$HERMES_USER"
fi
usermod -aG sudo "$HERMES_USER"

# --- 3. Create directories ---
echo "[3/12] Creating agent + business directories..."
mkdir -p "$HERMES_DIR"/{.hermes,.beads,skills,config,systemd,logs,vault,sql}
mkdir -p "$BUSINESS_DIR"
chown -R "$HERMES_USER:$HERMES_USER" "$HERMES_DIR"
chown -R "$HERMES_USER:$HERMES_USER" "$BUSINESS_DIR"

# --- 4. Install Hermes Agent ---
echo "[4/12] Installing Hermes Agent..."
sudo -u "$HERMES_USER" bash -c '
    python3 -m venv ~/hermes-venv
    source ~/hermes-venv/bin/activate
    pip install --upgrade pip
    pip install hermes-agent
'
ln -sf /home/hermes/hermes-venv/bin/hermes /usr/local/bin/hermes

# --- 5. Copy agent infra from install media ---
# The assistant/hermes-agent/ directory is copied or cloned to the VM first
echo "[5/12] Copying agent infrastructure..."
# If we're running from a cloned assistant repo:
if [ -d "/tmp/assistant/hermes-agent" ]; then
    cp -r /tmp/assistant/hermes-agent/* "$HERMES_DIR/"
    chown -R "$HERMES_USER:$HERMES_USER" "$HERMES_DIR"
fi

# --- 6. Clone business repos ---
echo "[6/12] Cloning business repositories..."
sudo -u "$HERMES_USER" git clone "$BUSINESS_REPO_URL" "$BUSINESS_DIR/ps3_labs_ai" || true
if [ -d "$BUSINESS_DIR/ps3_labs_ai/.git" ]; then
    sudo -u "$HERMES_USER" bash -c "cd $BUSINESS_DIR/ps3_labs_ai && git pull"
fi

# --- 7. Import existing leads ---
echo "[7/12] Importing existing leads..."
if [ -f "$BUSINESS_DIR/ps3_labs_ai/ahmedabad_b2b_leads.json" ]; then
    sudo -u "$HERMES_USER" bash -c "
        source ~/hermes-venv/bin/activate
        python $HERMES_DIR/scripts/import_leads.py \
            $BUSINESS_DIR/ps3_labs_ai/ahmedabad_b2b_leads.json
    " || true
fi

# --- 8. Install Node.js dependencies for WhatsApp ---
echo "[8/12] Installing Node.js dependencies..."
npm install -g @whiskeysockets/baileys || true

# --- 9. Set up SQLite CRM ---
echo "[9/12] Initializing CRM database..."
sudo -u "$HERMES_USER" sqlite3 "$HERMES_DIR/crm.db" < "$HERMES_DIR/sql/init_schema.sql"

# --- 10. Install systemd service ---
echo "[10/12] Installing systemd service..."
cp "$HERMES_DIR/systemd/hermes-gateway.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable hermes-gateway

# --- 11. Set up beads ---
echo "[11/12] Initializing beads..."
sudo -u "$HERMES_USER" bash -c '
    export BEADS_DIR=/opt/hermes-agent/.beads
    mkdir -p $BEADS_DIR/formulas
    ln -sf /opt/hermes-agent/beads/formulas/* $BEADS_DIR/formulas/
'

# --- 12. Permissions and final notes ---
echo "[12/12] Setting permissions..."
chmod 600 "$HERMES_DIR"/.hermes/.env 2>/dev/null || true
chmod 700 "$HERMES_DIR"/vault
cp "$HERMES_DIR/config/.env.template" "$HERMES_DIR/.hermes/.env.template"
cp "$HERMES_DIR/config/config.yaml" "$HERMES_DIR/.hermes/config.yaml"
cp "$HERMES_DIR/config/businesses.yaml" "$HERMES_DIR/.hermes/businesses.yaml"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "AGENT INFRA: $HERMES_DIR"
echo "BUSINESS REPOS: $BUSINESS_DIR"
echo ""
echo "NEXT STEPS:"
echo "1. Edit $HERMES_DIR/.hermes/.env with your actual secrets"
echo "2. Edit $HERMES_DIR/.hermes/businesses.yaml to add more ventures"
echo "3. Edit $HERMES_DIR/.hermes/config.yaml with Azure Foundry endpoint"
echo "4. Run: hermes model  # to configure Azure Foundry + Kimi K2.6"
echo "5. Run: hermes whatsapp  # to pair WhatsApp number"
echo "6. Run: sudo systemctl start hermes-gateway"
echo ""
echo "For help, see: $HERMES_DIR/docs/DEPLOY.md"
