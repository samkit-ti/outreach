# Outreach Agent - Azure Infrastructure

Terraform configuration to provision the entire Azure infrastructure for the outreach agent.

## What It Creates

| Resource | Purpose |
|---|---|
| Resource Group | Container for all resources |
| Virtual Network + Subnet | Private network for VM |
| Public IP | Static IP for SSH access |
| Network Security Group | Firewall rules (SSH:22, HTTPS:443) |
| Linux VM (Ubuntu 24.04) | Hermes agent host (B2ms by default) |
| System-Assigned Managed Identity | For Azure Foundry authentication |
| Cloud-init | Automated VM setup on first boot |

## Prerequisites

1. **Azure CLI installed**: `az --version`
2. **Logged in**: `az login`
3. **Terraform installed**: `terraform --version` (v1.5+)

## Quick Start

```bash
cd terraform/

# 1. Initialize Terraform
terraform init

# 2. Review what will be created
terraform plan

# 3. Create everything (takes ~5-10 minutes)
terraform apply

# 4. Save outputs
terraform output vm_public_ip > ../vm-ip.txt
terraform output -raw ssh_private_key > ../vm-key.pem
chmod 600 ../vm-key.pem
```

## Outputs

| Output | Description |
|---|---|
| `vm_public_ip` | VM public IP address |
| `ssh_command` | Command to SSH into VM |
| `vm_principal_id` | Managed Identity ID (for Azure AI User role) |
| `ssh_private_key` | Private key (if auto-generated) |

## Post-Provisioning Steps

### 1. Assign Azure AI User Role

The VM needs permission to access Azure AI Foundry:

```bash
# Get the principal ID
PRINCIPAL_ID=$(terraform output -raw vm_principal_id)

# Replace with your actual Foundry resource details
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Azure AI User" \
  --scope /subscriptions/<subscription-id>/resourceGroups/<foundry-rg>/providers/Microsoft.CognitiveServices/accounts/<foundry-name>
```

### 2. Add Deploy Key to GitHub

```bash
# Get the public key
cat ~/.ssh/id_ed25519.pub

# Add to GitHub: Settings → Deploy keys → Add deploy key
# Title: "Azure VM Outreach Agent"
# Allow write access: YES
```

### 3. Configure GitHub Actions Secrets

See `.github/BRANCH_PROTECTION.md` for required secrets.

## Destroy

```bash
cd terraform/
terraform destroy
```

## Customization

Edit `terraform.tfvars` to customize:

```hcl
# terraform.tfvars
location        = "centralindia"    # Closest to Ahmedabad
vm_size         = "Standard_B2ms"   # 2 vCPU, 8 GiB (~$45/mo)
admin_username  = "hermes"
github_repo_url = "https://github.com/samkitshah1262/outreach.git"
```

## Cost Estimate

| Resource | Monthly Cost |
|---|---|
| VM (B2ms, 24/7) | ~$45 |
| OS Disk (64GB) | ~$5 |
| Public IP | ~$3 |
| Network (egress) | ~$5-10 |
| **Total** | **~$58-63** |

## Troubleshooting

| Issue | Solution |
|---|---|
| `terraform apply` fails | Check `az account show` - are you logged in? |
| VM not reachable | Check NSG rules - is port 22 open? |
| Setup script failed | SSH and check `/var/log/hermes-setup.log` |
| Foundry auth fails | Verify Managed Identity role assignment |

---

*Infrastructure as Code | Outreach Agent v1.0*
