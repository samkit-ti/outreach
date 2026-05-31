#!/usr/bin/env bash
# =============================================================================
# Outreach Agent — VM Setup Script
# Run this on the VM after Terraform creates it
# =============================================================================
set -euo pipefail

HERMES_ROOT="/opt/hermes"
ACR_LOGIN_SERVER="${1:-}"

echo "=== Hermes VM Setup ==="
echo "ACR: $ACR_LOGIN_SERVER"

# Login to ACR
if [ -n "$ACR_LOGIN_SERVER" ]; then
    echo "Logging into ACR..."
    az acr login --name "$ACR_LOGIN_SERVER"
fi

# Ensure directories exist
mkdir -p "$HERMES_ROOT"/{profiles,shared,backups,data}
mkdir -p "$HERMES_ROOT/shared"/{skills,config,scripts}

# Create profile directories
for profile in default ps3labs-x ps3labs-linkedin; do
    mkdir -p "$HERMES_ROOT/profiles/$profile"/{.hermes,logs,cron}
done

# Copy configs
if [ -d "./config" ]; then
    cp -r ./config/* "$HERMES_ROOT/shared/config/"
fi
if [ -d "./skills" ]; then
    cp -r ./skills/* "$HERMES_ROOT/shared/skills/"
fi

# Create .env template if not exists
if [ ! -f "$HERMES_ROOT/shared/.env" ]; then
    cat > "$HERMES_ROOT/shared/.env" << 'EOF'
# Model Configuration
AZURE_FOUNDRY_BASE_URL=https://opencode-agent-resource.services.ai.azure.com/models
AZURE_FOUNDRY_API_KEY=<your-azure-ai-key>
DEFAULT_MODEL=Kimi-K2.6

# Messaging Platforms
TELEGRAM_BOT_TOKEN=<your-telegram-token>
TELEGRAM_ALLOW_ALL_USERS=true

# X/Twitter (for ps3labs-x profile)
X_API_KEY=<your-x-api-key>
X_API_SECRET=<your-x-api-secret>
X_ACCESS_TOKEN=<your-x-access-token>
X_ACCESS_SECRET=<your-x-access-secret>
X_BEARER_TOKEN=<your-x-bearer-token>

# LinkedIn (for ps3labs-linkedin profile)
LINKEDIN_CLIENT_ID=<your-linkedin-client-id>
LINKEDIN_CLIENT_SECRET=<your-linkedin-client-secret>
LINKEDIN_ACCESS_TOKEN=<your-linkedin-access-token>

# Founder
FOUNDER_EMAIL=samkit@ps3labs.ai

# Paths
HERMES_DIR=/app
HERMES_HOME=/app/.hermes
PYTHONPATH=/app

# Web Search
WEB_SEARCH_BACKEND=duckduckgo

# Optional enrichment APIs
EXA_API_KEY=
FIRECRAWL_API_KEY=
TAVILY_API_KEY=
CLEARBIT_API_KEY=
APOLLO_API_KEY=
HUNTER_API_KEY=
EOF
    echo "Created .env template at $HERMES_ROOT/shared/.env"
    echo "IMPORTANT: Edit this file with your actual secrets before starting!"
fi

# Set permissions
chown -R "${SUDO_USER:-$USER}:${SUDO_USER:-$USER}" "$HERMES_ROOT"

echo ""
echo "Setup complete! Next steps:"
echo "  1. Edit secrets: sudo nano $HERMES_ROOT/shared/.env"
echo "  2. Start services: cd $HERMES_ROOT && docker-compose up -d"
echo "  3. View logs: docker logs -f hermes-default"
echo ""
echo "Profiles configured:"
echo "  - default: General outreach + Telegram"
echo "  - ps3labs-x: X/Twitter posting and DMs"
echo "  - ps3labs-linkedin: LinkedIn posting and messaging"
