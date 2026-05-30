terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.75"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "azurerm" {
  features {}
}

# Variables
variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "app_name" {
  description = "Application name"
  type        = string
  default     = "outreach"
}

# Random suffix for unique names
resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
}

# Resource Group
resource "azurerm_resource_group" "outreach" {
  name     = "${var.app_name}-rg-${random_string.suffix.result}"
  location = var.location

  tags = {
    Project     = "outreach-agent"
    Environment = "production"
    ManagedBy   = "terraform"
  }
}

# Log Analytics Workspace (required for Container Apps)
resource "azurerm_log_analytics_workspace" "outreach" {
  name                = "${var.app_name}-logs-${random_string.suffix.result}"
  location            = azurerm_resource_group.outreach.location
  resource_group_name = azurerm_resource_group.outreach.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = {
    Project = "outreach-agent"
  }
}

# Storage Account for persistent data (SQLite, config)
resource "azurerm_storage_account" "outreach" {
  name                     = "${var.app_name}data${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.outreach.name
  location                 = azurerm_resource_group.outreach.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"

  tags = {
    Project = "outreach-agent"
  }
}

# File Share for persistent storage
resource "azurerm_storage_share" "outreach" {
  name                 = "outreach-data"
  storage_account_name = azurerm_storage_account.outreach.name
  quota                = 50 # GB
}

# Azure Container Registry
resource "azurerm_container_registry" "outreach" {
  name                = "${var.app_name}acr${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.outreach.name
  location            = azurerm_resource_group.outreach.location
  sku                 = "Basic"
  admin_enabled       = true

  tags = {
    Project = "outreach-agent"
  }
}

# Container App Environment
resource "azurerm_container_app_environment" "outreach" {
  name                       = "${var.app_name}-env-${random_string.suffix.result}"
  location                   = azurerm_resource_group.outreach.location
  resource_group_name        = azurerm_resource_group.outreach.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.outreach.id

  tags = {
    Project = "outreach-agent"
  }
}

# Mount the Azure Files share into the Container App Environment
resource "azurerm_container_app_environment_storage" "outreach" {
  name                         = "outreach-data"
  container_app_environment_id = azurerm_container_app_environment.outreach.id
  account_name                 = azurerm_storage_account.outreach.name
  share_name                   = azurerm_storage_share.outreach.name
  access_key                   = azurerm_storage_account.outreach.primary_access_key
  access_mode                  = "ReadWrite"
}

# Container App
resource "azurerm_container_app" "outreach" {
  name                         = "${var.app_name}-agent"
  container_app_environment_id = azurerm_container_app_environment.outreach.id
  resource_group_name          = azurerm_resource_group.outreach.name
  revision_mode                = "Single"

  secret {
    name  = "registry-password"
    value = azurerm_container_registry.outreach.admin_password
  }

  registry {
    server               = azurerm_container_registry.outreach.login_server
    username             = azurerm_container_registry.outreach.admin_username
    password_secret_name = "registry-password"
  }

  template {
    container {
      name   = "outreach-agent"
      image  = "${azurerm_container_registry.outreach.login_server}/outreach-agent:latest"
      cpu    = 0.5
      memory = "1Gi"

      # Mount persistent storage
      volume_mounts {
        name = "outreach-data"
        path = "/app/data"
      }

      env {
        name  = "PYTHONPATH"
        value = "/app"
      }

      env {
        name  = "DATA_DIR"
        value = "/app/data"
      }

      env {
        name  = "HERMES_DIR"
        value = "/app/data"
      }
    }

    volume {
      name         = "outreach-data"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.outreach.name
    }

    min_replicas = 1
    max_replicas = 1
  }

  # No ingress needed for a background worker

  tags = {
    Project     = "outreach-agent"
    Environment = "production"
  }

  depends_on = [azurerm_container_app_environment_storage.outreach]
}

# Outputs
output "resource_group_name" {
  value = azurerm_resource_group.outreach.name
}

output "acr_login_server" {
  value = azurerm_container_registry.outreach.login_server
}

output "acr_username" {
  value = azurerm_container_registry.outreach.admin_username
}

output "acr_password" {
  value     = azurerm_container_registry.outreach.admin_password
  sensitive = true
}

output "storage_account_name" {
  value = azurerm_storage_account.outreach.name
}

output "container_app_name" {
  value = azurerm_container_app.outreach.name
}

output "container_app_environment_name" {
  value = azurerm_container_app_environment.outreach.name
}

output "logs_command" {
  value = "az containerapp logs show --name ${azurerm_container_app.outreach.name} --resource-group ${azurerm_resource_group.outreach.name} --follow"
}
