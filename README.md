# Outreach Agent

Autonomous sales & marketing agent powered by Hermes + Azure AI Foundry (Kimi K2.6).

## What It Does

This agent handles the entire outreach lifecycle for your business:
- **Lead management** — Enrich, score, and track leads via SQLite CRM
- **Cold outreach** — Draft personalized emails and WhatsApp messages
- **Inbound handling** — Classify and auto-reply to incoming messages
- **Follow-ups** — Daily scheduled follow-ups for stale leads
- **Market research** — Weekly competitive intelligence reports
- **Self-improvement** — Evolution engine learns from every interaction

## Architecture

```
Azure VM (Ubuntu 24.04)
├── Hermes Gateway (persistent daemon)
│   ├── Email adapter (Gmail IMAP/SMTP)
│   ├── WhatsApp adapter (Baileys bridge)
│   └── Discord adapter (founder command center)
├── Kimi K2.6 via Azure Foundry
├── SQLite CRM (leads, interactions, rules)
├── Beads workflow engine (task tracking, formulas)
└── Custom skills (Python)
```

## Quick Deploy

```bash
# On a fresh Ubuntu 24.04 VM with sudo access:
sudo bash scripts/setup-vm.sh
```

See [docs/DEPLOY.md](docs/DEPLOY.md) for full setup instructions.

## Multi-Business Ready

The agent is designed to serve multiple ventures. Configure ventures in `config/businesses.yaml`.

Currently configured:
- `ps3_labs_ai` — AI agents for healthcare & education (Ahmedabad, India)

## Skills

| Skill | Purpose |
|---|---|
| `crm_toolkit` | Lead CRUD, interactions, approval queue |
| `outreach_drafter` | Personalized email/WhatsApp drafts |
| `inbox_classifier` | Intent classification + auto-reply decisions |
| `lead_enricher` | Web research to fill lead data gaps |
| `follow_up_scheduler` | Daily stale lead follow-ups |
| `pattern_extractor` | Weekly behavior pattern analysis |
| `market_research` | Competitive & industry intel |
| `evolution_engine` | Self-modifying behavior rules |

## Formulas

- `outreach-sequence` — Full lifecycle: enrich → draft → approve → send → log
- `inbound-handler` — Classify → context → draft → guardrail → send
- `weekly-evolution` — Analyze → extract patterns → propose rules → apply

## Cost Estimate

- Azure VM (B2ms): ~$45/month
- Kimi K2.6 inference: ~$40–100/month (variable)
- **Total: ~$85–145/month**

## Reference

- `AUTONOMOUS_DEV_TEAM.md` — Autonomous team architecture reference
- `design/` — Design docs (v1, v2, v3)

---

Built for PS3 Labs AI | Multi-venture ready
