#!/usr/bin/env bash
# =============================================================================
# Deploy Outreach Agent to Azure VM
# =============================================================================
set -euo pipefail

VM_HOST="${1:-}"
VM_USER="${2:-outreach}"
SSH_KEY="${3:-$HOME/.ssh/outreach-vm}"

if [ -z "$VM_HOST" ]; then
    echo "Usage: $0 <vm-host> [vm-user] [ssh-key-path]"
    echo "Example: $0 20.12.34.56 outreach ~/.ssh/outreach-vm"
    exit 1
fi

echo "=== Deploying to VM: $VM_HOST ==="

# Build and push image locally (or let CI handle it)
echo "Building and pushing Docker image..."
docker build -t outreach-agent:latest .

# SSH and deploy
echo "Deploying to VM..."
ssh -i "$SSH_KEY" \
    -o StrictHostKeyChecking=yes \
    "$VM_USER@$VM_HOST" << EOF
    cd /opt/hermes
    
    # Pull latest image
    docker-compose pull
    
    # Restart services
    docker-compose down
    docker-compose up -d
    
    # Verify
    docker ps --format "table {{.Names}}\t{{.Status}}"
EOF

echo "=== Deployment complete ==="
echo "View logs: ssh -i $SSH_KEY $VM_USER@$VM_HOST 'docker logs -f hermes-default'"
