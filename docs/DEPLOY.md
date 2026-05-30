# Hermes Agent — Multi-Business Deployment Guide

Deploy an autonomous Hermes agent that serves multiple business ventures from a single Azure VM. Each business gets its own Git repo; the agent infra lives in one place.

## Architecture

```
Azure VM
├── /opt/hermes-agent/        ← Agent infrastructure (this repo)
│   ├── .hermes/              # Config, sessions, .env
│   ├── .beads/               # Task tracking DB + formulas
│   ├── skills/               # Python skills
│   ├── crm.db                # Shared CRM database
│   ├── logs/                 # Service logs
│   └── systemd/              # Service files
│
├── /opt/business/            ← Business repos (cloned)
│   ├── ps3_labs_ai/          # PS3 Labs AI
│   │   ├── ahmedabad_b2b_leads.json
│   │   ├── outreach_strategy.md
│   │   ├── market_intel/
│   │   └── website/
│   └── future_venture/       # Add more here
│
└── /home/hermes/             # Hermes user home
    └── hermes-venv/          # Python virtualenv
```

## Prerequisites

- Azure subscription
- Azure AI Foundry resource with Kimi K2.6 deployed
- Dedicated Gmail account (2FA + App Password)
- Dedicated WhatsApp phone number
- Discord bot token

## Quick Start (One Command)

### 1. Prepare the VM

SSH into a fresh Ubuntu 24.04 VM:

```bash
ssh hermes@<your-vm-ip>
```

### 2. Copy Agent Infrastructure

Option A — Clone from GitHub:
```bash
git clone https://github.com/samkit-shah/assistant.git /tmp/assistant
```

Option B — SCP from your machine:
```bash
scp -r assistant/hermes-agent hermes@<vm-ip>:/tmp/assistant/
```

### 3. Run Setup

```bash
sudo bash /tmp/assistant/hermes-agent/scripts/setup-vm.sh
```

This script will:
1. Install Python, Node.js, SQLite, Git
2. Create `hermes` user
3. Install Hermes Agent in a virtualenv
4. Copy agent infrastructure to `/opt/hermes-agent/`
5. Clone `ps3_labs_ai` to `/opt/business/ps3_labs_ai`
6. Import existing leads
7. Initialize CRM database
8. Install systemd service
9. Set up beads + formulas

### 4. Configure Secrets

```bash
sudo nano /opt/hermes-agent/.hermes/.env
# Fill in EMAIL_PASSWORD, DISCORD_BOT_TOKEN, FOUNDER_EMAIL, etc.
```

### 5. Configure Azure Foundry

```bash
sudo -u hermes bash -c 'source ~/hermes-venv/bin/activate && hermes model'
# Select "Azure Foundry" → Enter endpoint → "Entra ID" → Select Kimi K2.6
```

### 6. Pair WhatsApp

```bash
sudo -u hermes bash -c 'source ~/hermes-venv/bin/activate && hermes whatsapp'
# Scan QR code with your bot's WhatsApp
```

### 7. Start Service

```bash
sudo systemctl start hermes-gateway
sudo systemctl status hermes-gateway
```

### 8. Verify

```bash
sudo -u hermes bash -c 'source ~/hermes-venv/bin/activate && hermes doctor'
```

---

## Daily Operations

### Check Status
```bash
sudo systemctl status hermes-gateway
sudo journalctl -u hermes-gateway -f
```

### View Pending Approvals
```bash
sudo -u hermes sqlite3 /opt/hermes-agent/crm.db \
  "SELECT * FROM pending_actions WHERE status='pending' ORDER BY urgency;"
```

### Trigger Follow-ups Manually
```bash
sudo -u hermes bash -c 'source ~/hermes-venv/bin/activate && \
  python /opt/hermes-agent/skills/follow_up_scheduler.py'
```

### Deploy Updates
```bash
sudo bash /opt/hermes-agent/scripts/deploy.sh
```

---

## Adding a New Business

1. **Add to manifest**:
```bash
sudo nano /opt/hermes-agent/.hermes/businesses.yaml
```
Add a new entry under `businesses:`.

2. **Clone the business repo**:
```bash
cd /opt/business
git clone https://github.com/samkit-shah/future_venture.git
```

3. **Import leads** (if any):
```bash
python /opt/hermes-agent/scripts/import_leads.py \
  /opt/business/future_venture/leads.json
```

4. **Restart agent**:
```bash
sudo systemctl restart hermes-gateway
```

The agent will now use the appropriate business context based on the active business setting in `.env` (`ACTIVE_BUSINESS=future_venture`).

---

## Directory Reference

| Path | Purpose |
|---|---|
| `/opt/hermes-agent/` | Agent installation (skills, configs, CRM, beads) |
| `/opt/hermes-agent/.hermes/` | Hermes config, sessions, env |
| `/opt/hermes-agent/.beads/` | Beads task DB + formulas |
| `/opt/hermes-agent/crm.db` | SQLite CRM (shared across businesses) |
| `/opt/hermes-agent/skills/` | Python skill source files |
| `/opt/hermes-agent/logs/` | Gateway logs |
| `/opt/business/ps3_labs_ai/` | PS3 Labs AI business repo |
| `/opt/business/*/market_intel/` | Market research reports per business |

---

## Troubleshooting

| Problem | Solution |
|---|---|
| 401 on Foundry | Check Managed Identity role assignment; wait 5 min |
| WhatsApp not working | Re-pair: `hermes whatsapp`; check session dir |
| Emails not threading | Verify SMTP settings; check spam |
| Service won't start | `journalctl -u hermes-gateway -n 50`; check `.env` perms (chmod 600) |
| High API costs | Check `monthly_cost` view in CRM; review cron frequency |
| Business repo not found | Verify `BUSINESS_DIR` and `ACTIVE_BUSINESS` in `.env` |

---

## Security Checklist

- [ ] `.env` is chmod 600
- [ ] WhatsApp session dir is chmod 700
- [ ] Vault dir is encrypted (encfs/gocryptfs)
- [ ] VM has only SSH key auth (no password)
- [ ] Azure AI User role restricted to Foundry resource only
- [ ] Discord bot uses DM-only mode
- [ ] Email allowlist configured

---

## Next Steps

1. [ ] Test inbound email → auto-reply flow
2. [ ] Test WhatsApp message → response flow
3. [ ] Test Discord command → agent action
4. [ ] Queue a test follow-up manually
5. [ ] Verify daily cron at 9 AM IST
6. [ ] Wait 1 week for first pattern extraction
7. [ ] Review evolution rules in Discord
8. [ ] Add second business repo (if ready)

---

*Deployment Guide v2.0 | Multi-Business | 2026-05-30*
