#!/bin/bash
set -euo pipefail

echo "=== Outreach Agent Container Build & Deploy ==="

# Get ACR details from Terraform
ACR_LOGIN_SERVER=$(terraform output -raw acr_login_server)
ACR_USERNAME=$(terraform output -raw acr_username)
ACR_PASSWORD=$(terraform output -raw acr_password)
RESOURCE_GROUP=$(terraform output -raw resource_group_name)
CONTAINER_APP=$(terraform output -raw container_app_name)

echo "Building Docker image..."
docker build -t "${ACR_LOGIN_SERVER}/outreach-agent:latest" ..

echo "Logging into Azure Container Registry..."
echo "$ACR_PASSWORD" | docker login "$ACR_LOGIN_SERVER" -u "$ACR_USERNAME" --password-stdin

echo "Pushing image to ACR..."
docker push "${ACR_LOGIN_SERVER}/outreach-agent:latest"

echo "Updating Container App..."
az containerapp update \
  --name "$CONTAINER_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --image "${ACR_LOGIN_SERVER}/outreach-agent:latest"

echo "Done! View logs with:"
echo "  az containerapp logs show --name $CONTAINER_APP --resource-group $RESOURCE_GROUP --follow"
