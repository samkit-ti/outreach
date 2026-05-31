# =============================================================================
# Outreach Agent — Azure VM Edition
# Multi-profile, SSH-accessible, persistent storage
# =============================================================================

# SSH Public Key — generate locally with: ssh-keygen -t rsa -b 4096 -f ~/.ssh/outreach-vm
variable "ssh_public_key_path" {
  description = "Path to SSH public key for VM access"
  type        = string
  default     = "~/.ssh/outreach-vm.pub"
}

variable "vm_size" {
  description = "Azure VM SKU"
  type        = string
  default     = "Standard_B2ms"  # 2 vCPU, 8 GB RAM, ~$60/mo
}

variable "vm_admin_username" {
  description = "Admin username for VM"
  type        = string
  default     = "outreach"
}

# Virtual Network
resource "azurerm_virtual_network" "outreach" {
  name                = "${var.app_name}-vnet-${random_string.suffix.result}"
  address_space       = ["10.0.0.0/16"]
  location            = azurerm_resource_group.outreach.location
  resource_group_name = azurerm_resource_group.outreach.name
}

# Subnet
resource "azurerm_subnet" "outreach" {
  name                 = "${var.app_name}-subnet-${random_string.suffix.result}"
  resource_group_name  = azurerm_resource_group.outreach.name
  virtual_network_name = azurerm_virtual_network.outreach.name
  address_prefixes     = ["10.0.1.0/24"]
}

# Public IP
resource "azurerm_public_ip" "outreach" {
  name                = "${var.app_name}-ip-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.outreach.name
  location            = azurerm_resource_group.outreach.location
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = {
    Project = "outreach-agent"
  }
}

# Network Security Group
resource "azurerm_network_security_group" "outreach" {
  name                = "${var.app_name}-nsg-${random_string.suffix.result}"
  location            = azurerm_resource_group.outreach.location
  resource_group_name = azurerm_resource_group.outreach.name

  # SSH
  security_rule {
    name                       = "SSH"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  # Webhook ports (Telegram, etc.)
  security_rule {
    name                       = "Webhooks"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  tags = {
    Project = "outreach-agent"
  }
}

# Network Interface
resource "azurerm_network_interface" "outreach" {
  name                = "${var.app_name}-nic-${random_string.suffix.result}"
  location            = azurerm_resource_group.outreach.location
  resource_group_name = azurerm_resource_group.outreach.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.outreach.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.outreach.id
  }
}

# Associate NSG with NIC
resource "azurerm_network_interface_security_group_association" "outreach" {
  network_interface_id      = azurerm_network_interface.outreach.id
  network_security_group_id = azurerm_network_security_group.outreach.id
}

# Cloud-init: Install Docker, Docker Compose, create directories
locals {
  cloud_init = base64encode(templatefile("${path.module}/cloud-init.yaml", {
    admin_user = var.vm_admin_username
  }))
}

# Linux VM
resource "azurerm_linux_virtual_machine" "outreach" {
  name                = "${var.app_name}-vm-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.outreach.name
  location            = azurerm_resource_group.outreach.location
  size                = var.vm_size
  admin_username      = var.vm_admin_username

  network_interface_ids = [azurerm_network_interface.outreach.id]

  admin_ssh_key {
    username   = var.vm_admin_username
    public_key = file(var.ssh_public_key_path)
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 128
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  custom_data = local.cloud_init

  tags = {
    Project     = "outreach-agent"
    Environment = "production"
  }
}

# Managed Disk for persistent data (mounted at /opt/hermes/data)
resource "azurerm_managed_disk" "outreach_data" {
  name                 = "${var.app_name}-data-disk-${random_string.suffix.result}"
  location             = azurerm_resource_group.outreach.location
  resource_group_name  = azurerm_resource_group.outreach.name
  storage_account_type = "StandardSSD_LRS"
  create_option        = "Empty"
  disk_size_gb         = 64

  tags = {
    Project = "outreach-agent"
  }
}

resource "azurerm_virtual_machine_data_disk_attachment" "outreach_data" {
  managed_disk_id    = azurerm_managed_disk.outreach_data.id
  virtual_machine_id = azurerm_linux_virtual_machine.outreach.id
  lun                = "10"
  caching            = "ReadWrite"
}

# Container Registry (kept for building/pushing images)
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

# Storage Account (kept for backups)
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

# Outputs
output "vm_public_ip" {
  value = azurerm_public_ip.outreach.ip_address
}

output "vm_ssh_command" {
  value = "ssh ${var.vm_admin_username}@${azurerm_public_ip.outreach.ip_address} -i ~/.ssh/outreach-vm"
}

output "vm_fqdn" {
  value = azurerm_public_ip.outreach.fqdn
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
