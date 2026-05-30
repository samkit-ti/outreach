# Design v2: Hermes Agent on Azure AI Foundry — Evolving Sales/Marketing Team for PS3Labs

**Reference:** `AUTONOMOUS_DEV_TEAM.md` (this repo) — defines the autonomous team architecture, persona model, beads integration, and evolution engine.

**Date:** 2026-05-29  
**Status:** Design Complete — Awaiting Founder Decisions  
**Designer:** Hermes AI  

---

## Summary of Changes from v1

| Dimension | v1 (Previous) | v2 (This Design) |
|---|---|---|
| **Compute** | Azure Container Apps (serverless, ~$15/mo) | **Azure VM** (persistent, full control, ~$35–55/mo) |
| **Primary LLM** | Tiered: Phi-4 (default) + Llama 4 Scout (heavy) + DeepSeek-R1 (reasoning) | **Kimi K2.6** (single powerful model, all tasks) |
| **Task Tracking** | Implicit (cron jobs, loose files) | **Beads** — explicit issues, formulas, dependencies |
| **Memory** | Filesystem + ad-hoc | **Beads memories + evolution engine + curated MEMORY.md** |
| **Adaptability** | Static skills | **Self-modifying** — learns from every client interaction and founder feedback |
| **Architecture** | Single gateway + cron jobs | **Multi-persona autonomous team** (Sales + Marketing + Research) |
| **Channels** | Email + WhatsApp (basic) | Email + WhatsApp + Discord (for founder comms) |

---

## 1. Decision Questions & Resolutions

### Q1: Why Azure VM over Container Apps?

**Answer:** You approved the budget (~$30–60/mo). A VM buys us:
- **Full filesystem persistence** — no volume-mount complexity; `~/.hermes/`, beads DB, CRM SQLite, and logs just live on disk.
- **Systemd service** — `hermes gateway` runs as a native system service with `restart=always`. No container orchestration quirks.
- **Direct WhatsApp bridge** — Baileys (Node.js) runs alongside the Python gateway in the same OS. No cross-container networking.
- **Beads native** — The beads CLI + SQLite store runs directly on the filesystem without container abstraction.
- **SSH access** — You can SSH in, run `bd ready`, check logs, debug directly.

**Recommended VM spec:** Azure B2s (2 vCPU, 4 GiB RAM, ~$30/mo) or Standard_B2ms (2 vCPU, 8 GiB, ~$45/mo) if we run occasional background analysis jobs concurrently. Ubuntu 24.04 LTS.

### Q2: Why Kimi K2.6 as the single model?

**Answer:** You confirmed Azure Foundry provides Kimi K2.6. Kimi models (by Moonshot AI) are known for:
- **Very long context** (200K+ tokens) — can ingest entire lead databases, long email threads, or market research reports in one prompt.
- **Strong instruction following** — good for structured output (CRM updates, JSON responses).
- **Multilingual** — solid on English, Hindi, Gujarati (relevant for Ahmedabad market).
- **Open-weight ethos** — cheaper than GPT-4o/Claude Sonnet, close in capability.

**Cost estimate:** Kimi K2.6 on Azure Foundry is roughly **$0.50–1.00 / 1M input tokens** and **$1.50–3.00 / 1M output tokens** (check exact pricing in your Foundry portal). For a sales agent doing ~100–200 interactions/day with rich context, expect **$30–80/month in inference**.

**No model tiering needed.** Kimi K2.6 handles both quick replies and deep analysis. Simpler config, less code.

### Q3: How does Beads integrate into the agent?

**Answer:** Beads is not just the human's project tracker — it is the **agent's operational brain.**

The agent:
1. **Creates beads** for every task it discovers (`bd create "Follow up with Apollo Hospitals" -t task -p 1`)
2. **Claims beads** before starting work (`bd update <id> --claim`)
3. **Closes beads** when done (`bd close <id>`)
4. **Uses formulas** for repeatable workflows (`bd mol pour outreach-sequence`)
5. **Stores memories** via `bd remember` ("Apollo prefers WhatsApp")
6. **Reads dependencies** to know what's blocked (`bd ready`)

This means the agent's work is **visible, auditable, and resumable** — just like a human on your team.

### Q4: How does the system "evolve?"

**Answer:** Via the **Evolution Engine** (detailed in AUTONOMOUS_DEV_TEAM.md). In short:

1. **Log** every client interaction as a structured event.
2. **Track** outcomes (reply, ignore, meeting, closed-won, objection).
3. **Extract** patterns weekly: "WhatsApp follow-ups get 2x replies for healthcare leads under ₹1L."
4. **Self-modify**: Write a rule to `evolution_rules.json` that changes the agent's behavior.
5. **Founder feedback**: Your corrections are highest-priority signals that immediately update rules.

The agent literally becomes smarter about your specific market over time — without code deployments.

### Q5: Why Discord as a founder channel?

**Answer:** You already have OpenClaw + Discord wired for PS3Labs (`SETUP.md`). Discord becomes the **command center** where you:
- Approve/reject pending agent actions
- Give feedback on drafts
- Receive daily/weekly digests
- Issue one-off research commands

The agent can send messages to your Discord DM or the `#ps3labs` channel via Hermes' Discord adapter.

---

## 2. Architecture Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Founder as Founder (Discord / Email)
    actor Client as Client (Email / WhatsApp)
    participant VM as Azure VM (Ubuntu + systemd)
    participant HG as Hermes Gateway
    participant Beads as Beads (Task & Memory)
    participant Evo as Evolution Engine
    participant Foundry as Azure AI Foundry (Kimi K2.6)
    participant CRM as CRM SQLite
    participant Files as /workspace/ps3_labs_ai (Git)

    %% === INBOUND CLIENT EMAIL ===
    Client->>VM: Email to sales@ps3labs.ai
    VM->>HG: Email adapter (IMAP poll)
    HG->>HG: Persona Router: Sales
    HG->>Beads: bd create "Inbound: Apollo Hospitals pricing inquiry"
    HG->>CRM: Lookup lead by email domain
    HG->>Files: Read outreach_strategy.md, pricing docs
    HG->>Beads: bd remember query: "Apollo Hospitals preferences"
    Beads-->>HG: "Prefers WhatsApp; last touch: 2026-05-20"
    HG->>Foundry: Kimi K2.6: classify + draft reply
    Foundry-->>HG: Reply draft + classification: "pricing_objection"

    alt High-stakes or first contact
        HG->>Founder: Discord DM: "Draft reply ready. /approve or /edit?"
        Founder-->>HG: /approve
    else Routine reply
        HG->>HG: Auto-send (within guardrails)
    end

    HG->>Client: SMTP reply (threaded)
    HG->>CRM: Log interaction (outbound reply, template v3)
    HG->>Evo: Emit event: {lead, channel, type, outcome: "pending"}
    HG->>Beads: bd close <inbound_task_id>

    %% === INBOUND CLIENT WHATSAPP ===
    Client->>VM: WhatsApp message
    VM->>HG: Baileys WebSocket event
    HG->>HG: Persona Router: Sales
    HG->>CRM: Lookup lead by phone
    HG->>Foundry: Kimi K2.6: context-aware reply
    Foundry-->>HG: Reply
    HG->>Client: WhatsApp reply
    HG->>CRM: Log interaction
    HG->>Evo: Emit event

    %% === DAILY CRON: FOLLOW-UP SCHEDULER ===
    loop Every day at 09:00 IST
        VM->>HG: Cron trigger
        HG->>CRM: SELECT leads WHERE last_contact > 5 days AND status != 'closed'
        HG->>Beads: bd ready (check existing tasks)
        HG->>Foundry: Kimi K2.6: "Which leads need follow-up? Draft messages."
        Foundry-->>HG: List of leads + draft messages
        HG->>Beads: bd create "Follow-up: 12 leads queued" -t task

        alt Auto-send threshold
            HG->>Client: Send scheduled messages (Email/WhatsApp)
            HG->>CRM: Log "follow_up_sent"
        else Human approval
            HG->>Founder: Discord: "12 follow-ups ready. /send_all or review?"
        end
    end

    %% === WEEKLY EVOLUTION CYCLE ===
    loop Every Monday at 10:00 IST
        VM->>HG: Cron trigger: pattern_extractor
        HG->>CRM: SELECT * FROM interactions WHERE week = last_week
        HG->>Evo: Run pattern analysis
        Evo-->>HG: Extracted rules: ["prefer_whatsapp_for_healthcare_lt_1L"]
        HG->>Evo: Write to evolution_rules.json
        HG->>Founder: Discord: "📊 Weekly learnings: 3 new behavior rules applied. Review?"
    end

    %% === FOUNDER FEEDBACK LOOP ===
    Founder->>HG: Discord: "That message was too pushy. Softer for education leads."
    HG->>Evo: Founder_feedback event: {tone: "softer", icp: "education"}
    HG->>Evo: Immediate rule injection
    Evo->>HG: Updated system prompt for Education ICP
    HG->>Beads: bd remember "Founder prefers softer tone for education leads"
    HG->>Founder: Discord: "✅ Rule applied. Future education outreach will be softer."

    %% === RESEARCH / MARKET INTEL ===
    loop Every Monday at 11:00 IST
        VM->>HG: Cron trigger: market_research
        HG->>HG: Persona Router: Research
        HG->>Foundry: Kimi K2.6: "Analyze last week's competitor/industry news"
        HG->>Files: Write report to market_intel/YYYY-MM-DD.md
        HG->>Founder: Discord: "📈 Weekly market intel ready."
    end
```

---

## 3. Component Specification

### 3.1 Azure VM

```yaml
# Terraform / ARM conceptual
resource "azurerm_linux_virtual_machine" "ps3labs_hermes" {
  name                = "ps3labs-hermes-vm"
  resource_group_name = "ps3labs-rg"
  location            = "Central India"  # Closest to Ahmedabad
  size                = "Standard_B2ms"   # 2 vCPU, 8 GiB
  admin_username      = "hermes"

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 64
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-noble"
    sku       = "24_04-lts"
    version   = "latest"
  }

  # System-Assigned Managed Identity for Azure Foundry auth
  identity {
    type = "SystemAssigned"
  }
}

# Post-provisioning: assign Azure AI User role on Foundry resource
# az role assignment create \
#   --assignee <vm-principal-id> \
#   --role "Azure AI User" \
#   --scope <foundry-resource-id>
```

### 3.2 Hermes Configuration (`~/.hermes/config.yaml`)

```yaml
model:
  provider: azure-foundry
  base_url: https://<your-resource>.openai.azure.com/openai/v1
  api_mode: chat_completions
  auth_mode: entra_id          # Managed Identity — no API key in config
  default: kimi-k2-6
  context_length: 200000       # Kimi K2.6 long context
  entra:
    scope: https://ai.azure.com/.default

gateway:
  platforms:
    email:
      poll_interval: 15
      allowed_users:
        - samkit@ps3labs.ai
        # Add other trusted domains here
    whatsapp:
      mode: bot
      allowed_users: "*"          # Lock down to specific numbers after testing
      unauthorized_dm_behavior: ignore
    discord:
      token_env: DISCORD_BOT_TOKEN
      allowed_users:
        - <your-discord-user-id>
      dm_only: true               # Only respond in DMs, not public servers

display:
  tool_progress: new
  busy_ack_enabled: true
  busy_ack_detail: false        # Terse on mobile

cron:
  jobs:
    - name: follow_up_scheduler
      schedule: "0 9 * * *"       # 9:00 AM IST daily
      command: "python /opt/ps3labs/skills/follow_up_scheduler.py"
    - name: pattern_extractor
      schedule: "0 10 * * 1"      # 10:00 AM IST Mondays
      command: "python /opt/ps3labs/skills/pattern_extractor.py"
    - name: market_research
      schedule: "0 11 * * 1"      # 11:00 AM IST Mondays
      command: "python /opt/ps3labs/skills/market_research.py"
    - name: git_sync
      schedule: "0 2 * * *"       # 2:00 AM IST daily: sync CRM + logs to Git
      command: "cd /workspace/ps3_labs_ai && git add -A && git commit -m 'auto: daily sync' && git push"
```

### 3.3 Beads Workspace (`~/.beads/` or `/opt/ps3labs/.beads/`)

Beads stores its SQLite DB and config on the VM's persistent disk. Backed up to Git nightly.

```bash
# Initialize
export BEADS_DIR=/opt/ps3labs/.beads
bd init $BEADS_DIR

# Formulas (reusable workflows live in Git, symlinked)
ln -s /workspace/ps3_labs_ai/beads/formulas $BEADS_DIR/formulas
```

### 3.4 CRM Schema (SQLite: `/opt/ps3labs/crm.db`)

```sql
CREATE TABLE leads (
    id TEXT PRIMARY KEY,           -- e.g., "apollo-ahmedabad-01"
    company_name TEXT,
    contact_name TEXT,
    email TEXT,
    phone TEXT,
    industry TEXT,                 -- healthcare | education | general
    source TEXT,                   -- inbound | outbound | referral | event
    status TEXT,                   -- new | contacted | engaged | meeting | proposal | closed_won | closed_lost | nurture
    priority INTEGER,              -- 0-4 (P0-P4)
    assigned_persona TEXT,         -- sales | marketing | research
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    evolution_rules TEXT           -- JSON: agent-learned preferences for this lead
);

CREATE TABLE interactions (
    id TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES leads(id),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    channel TEXT,                  -- email | whatsapp | discord | manual
    direction TEXT,                -- inbound | outbound
    message_type TEXT,             -- cold_outreach | follow_up | reply | pricing_objection | meeting_request | etc.
    content_preview TEXT,          -- First 200 chars
    template_id TEXT,              -- Which template/version was used
    sentiment TEXT,                -- positive | neutral | negative
    outcome TEXT,                  -- pending | replied | ignored | meeting_booked | closed_won | closed_lost | unsubscribed
    time_to_reply_hours INTEGER,
    final_value_inr INTEGER,
    founder_feedback TEXT          -- If founder manually reviewed
);

CREATE TABLE pending_actions (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    action_type TEXT,              -- send_message | publish_content | update_lead | modify_rule
    description TEXT,
    payload TEXT,                  -- JSON: draft message, content, etc.
    urgency INTEGER,               -- 0-4
    approved_by TEXT,              -- NULL until approved
    approved_at TIMESTAMP,
    rejected_reason TEXT
);

CREATE TABLE evolution_rules (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT,                   -- pattern_extractor | founder_feedback | manual
    confidence REAL,               -- 0.0-1.0
    condition TEXT,                -- Human-readable condition
    action TEXT,                   -- What to do
    priority TEXT,                 -- low | medium | high | critical
    expires_at TIMESTAMP,          -- Rules auto-expire to prevent stale behavior
    hit_count INTEGER DEFAULT 0    -- How many times this rule fired
);
```

### 3.5 File Layout on VM

```
/opt/ps3labs/
├── .hermes/                    # Hermes config, sessions, gateway state
│   ├── config.yaml
│   ├── .env
│   ├── platforms/
│   │   └── whatsapp/session/   # Baileys session (persistent!)
│   └── logs/
├── .beads/                     # Beads SQLite DB + formulas
│   ├── beads.db
│   └── formulas/
│       ├── outreach-sequence.formula.json
│       ├── weekly-market-scan.formula.json
│       └── lead-enrichment.formula.json
├── crm.db                      # SQLite CRM
├── evolution_rules.json        # Active learned rules
├── skills/                     # Custom Python skills
│   ├── __init__.py
│   ├── crm_toolkit.py
│   ├── outreach_drafter.py
│   ├── lead_enricher.py
│   ├── follow_up_scheduler.py
│   ├── inbox_classifier.py
│   ├── pattern_extractor.py
│   ├── market_research.py
│   └── evolution_engine.py
└── systemd/
    └── hermes-gateway.service   # Systemd unit file

/workspace/ps3_labs_ai/         # Git clone (read-write synced nightly)
├── ahmedabad_b2b_leads.json
├── outreach_strategy.md
├── market_intel/
│   └── YYYY-MM-DD.md
├── design/
├── website/
└── .git/
```

---

## 4. Persona System Prompts

These are injected based on the router's classification of the incoming message or cron job.

### Persona: Sales

```
You are the Sales Lead at PS3 Labs AI. Your job is to qualify leads, nurture relationships, and move prospects through the pipeline.

CONTEXT:
- PS3 Labs AI builds AI agents for healthcare and education in India.
- Pricing tiers: Starter ₹15K/mo, Professional ₹45K/mo, Enterprise ₹1.5L+/mo.
- Based in Ahmedabad, Gujarat. We serve pan-India.
- Key differentiators: vertical expertise (healthcare + education), DPDP compliance, Gujarati language support, affordable pricing for Indian SMBs.

YOUR CAPABILITIES:
- Read and update the CRM.
- Draft personalized outreach emails and WhatsApp messages.
- Handle pricing objections, schedule meetings, and send proposals.
- Identify high-intent signals (budget mentions, timeline urgency, decision-maker access).

TONE:
- Professional but warm. Not robotic, not overly salesy.
- Use Indian business English naturally.
- For healthcare leads: emphasize ROI, compliance, and patient outcomes.
- For education leads: emphasize personalization, scale, and student outcomes.

GUARDRAILS:
- Never promise features we don't have.
- Pricing quotes are suggestions; always note "final pricing subject to discussion."
- Never send more than 50 cold emails per day without human approval.
- Log every interaction to the CRM immediately.
- If a lead asks something you don't know, say you'll get back to them — don't hallucinate.
```

### Persona: Marketing

```
You are the Marketing Lead at PS3 Labs AI. Your job is to build awareness, create content, and generate inbound leads.

CONTEXT:
- Target ICPs: Private hospitals, diagnostic labs, K-12 schools, coaching institutes, EdTech platforms in India.
- Key channels: LinkedIn, email newsletters, WhatsApp broadcasts, industry events.
- Brand voice: Smart, approachable, technically credible but not jargon-heavy.

YOUR CAPABILITIES:
- Research competitors and industry trends.
- Draft LinkedIn posts, blog outlines, case studies, and email newsletters.
- Analyze campaign performance (open rates, click rates, lead gen).
- Identify content gaps and trending topics.

TONE:
- Thought-leadership style. Share insights, not just product pitches.
- Data-backed claims when possible.
- Occasional humor is okay — we're a young company.

GUARDRAILS:
- All public content requires human approval before publishing.
- Never make claims about competitors that aren't factual.
- Respect copyright — don't copy content verbatim.
```

### Persona: Research

```
You are the Market Intelligence Lead at PS3 Labs AI. Your job is to find new opportunities, enrich leads, and keep the team ahead of market shifts.

CONTEXT:
- Monitor: Healthcare AI adoption in India, EdTech policy changes, competitor moves, RFPs, funding news.
- Geography: India-first, with eye on Middle East and Southeast Asia for future expansion.

YOUR CAPABILITIES:
- Enrich lead records with web research (company size, tech stack, recent news).
- Scout RFPs, tenders, and procurement notices.
- Track competitor pricing, feature launches, and hiring.
- Map industry trends to PS3 Labs AI opportunities.

TONE:
- Analytical, concise, actionable.
- Reports should have a 1-sentence TL;DR, then supporting evidence.

GUARDRAILS:
- Respect robots.txt. No scraping behind paywalls.
- Distinguish between confirmed facts and inferred hypotheses.
- Rate-limit web searches to avoid blocking.
```

---

## 5. The Evolution Engine (Deep Dive)

### 5.1 Data Flow

```
┌───────────────────────────────────────────────────────────────┐
│                    INTERACTION LAYER                           │
│  (Every email, WhatsApp, Discord msg is logged)               │
└────────────────────┬──────────────────────────────────────────┘
                     │ structured_event
                     ▼
┌───────────────────────────────────────────────────────────────┐
│                    CRM + OUTCOME TRACKER                       │
│  (As interactions resolve, outcomes are attached)             │
└────────────────────┬──────────────────────────────────────────┘
                     │ weekly_batch
                     ▼
┌───────────────────────────────────────────────────────────────┐
│                    PATTERN EXTRACTOR                           │
│  Kimi K2.6 prompt: "Analyze these 200 interactions.            │
│  What worked? What failed? What patterns emerge?"             │
│  Output: ranked list of behavioral hypotheses                 │
└────────────────────┬──────────────────────────────────────────┘
                     │ high-confidence patterns
                     ▼
┌───────────────────────────────────────────────────────────────┐
│                    SELF-MODIFIER                               │
│  - Writes evolution_rules.json entries                        │
│  - Updates persona prompts (e.g., tone rules)                 │
│  - Suggests template improvements                             │
└────────────────────┬──────────────────────────────────────────┘
                     │ founder_review (optional)
                     ▼
┌───────────────────────────────────────────────────────────────┐
│                    HUMAN OVERRIDE                              │
│  Founder can approve, reject, or modify any rule.             │
│  Founder feedback creates immediate rules (no weekly wait).   │
└───────────────────────────────────────────────────────────────┘
```

### 5.2 Example Evolution Cycle

**Week 1:** Agent sends 50 cold emails using template v1. 2 replies (4% reply rate). Both from healthcare leads.

**Week 1 Pattern Extractor:**
- "Healthcare leads reply at 8% vs education at 2%"
- "Emails sent at 10 AM IST get 2x replies vs 2 PM"
- "Subject lines with 'AI automation' outperform 'AI agents' by 3pp"

**Self-Modifier creates rules:**
```json
{"id": "evr-001", "condition": "lead.industry == 'healthcare'", "action": "increase_priority_to_P2", "confidence": 0.72}
{"id": "evr-002", "condition": "outreach.channel == 'email'", "action": "schedule_send_at_10am_ist", "confidence": 0.81}
{"id": "evr-003", "condition": "draft.subject_contains('AI agents')", "action": "suggest_replacement('AI automation')", "confidence": 0.65}
```

**Week 2:** Agent applies rules. 50 emails sent. 5 replies (10% reply rate). Improvement validated.

**Founder Discord:** "The education outreach is too technical. Parents don't care about LLMs."

**Immediate rule:**
```json
{"id": "evr-004", "source": "founder_feedback", "condition": "lead.industry == 'education' AND lead.type == 'k12_school'", "action": "tone = 'simple_benefit_focused'; avoid_technical_jargon = true", "priority": "critical"}
```

---

## 6. Beads Formulas (Reusable Workflows)

### Formula 1: `outreach-sequence`

```json
{
  "name": "outreach-sequence",
  "description": "Full lifecycle of a single outreach attempt",
  "steps": [
    { "step": 1, "title": "Enrich Lead", "skill": "lead_enricher", "auto": true, "output": "enriched_lead" },
    { "step": 2, "title": "Score Lead", "skill": "lead_scorer", "auto": true, "input": "enriched_lead", "output": "lead_score" },
    { "step": 3, "title": "Draft Outreach", "skill": "outreach_drafter", "auto": true, "input": "enriched_lead", "output": "draft_message" },
    { "step": 4, "title": "Apply Evolution Rules", "skill": "evolution_engine", "auto": true, "input": "draft_message", "output": "optimized_draft" },
    { "step": 5, "title": "Human Approval Gate", "gate": "human_approve", "auto": false, "condition": "lead.priority >= 2 OR message.is_cold_outbound", "input": "optimized_draft" },
    { "step": 6, "title": "Send Message", "skill": "send_message", "auto": true, "input": "approved_draft" },
    { "step": 7, "title": "Log to CRM", "skill": "crm_log", "auto": true },
    { "step": 8, "title": "Schedule Follow-up", "skill": "follow_up_scheduler", "auto": true }
  ]
}
```

### Formula 2: `inbound-handler`

```json
{
  "name": "inbound-handler",
  "description": "Process any inbound message from a lead",
  "steps": [
    { "step": 1, "title": "Classify Intent", "skill": "inbox_classifier", "auto": true, "output": "intent" },
    { "step": 2, "title": "Load Context", "skill": "crm_toolkit", "auto": true, "output": "lead_context" },
    { "step": 3, "title": "Draft Response", "skill": "outreach_drafter", "auto": true, "input": ["intent", "lead_context"], "output": "draft_reply" },
    { "step": 4, "title": "Check Guardrails", "skill": "guardrail_checker", "auto": true, "input": "draft_reply", "output": "safe_to_send" },
    { "step": 5, "title": "Send or Queue", "skill": "send_or_queue", "auto": true, "condition": "safe_to_send == true AND lead.status != 'cold'" },
    { "step": 6, "title": "Log Interaction", "skill": "crm_log", "auto": true }
  ]
}
```

### Formula 3: `weekly-evolution`

```json
{
  "name": "weekly-evolution",
  "description": "Analyze week, extract patterns, evolve rules",
  "steps": [
    { "step": 1, "title": "Fetch Interactions", "skill": "crm_toolkit", "auto": true, "output": "interaction_batch" },
    { "step": 2, "title": "Analyze Patterns", "skill": "pattern_extractor", "auto": true, "input": "interaction_batch", "output": "patterns" },
    { "step": 3, "title": "Draft New Rules", "skill": "evolution_engine", "auto": true, "input": "patterns", "output": "proposed_rules" },
    { "step": 4, "title": "Human Review Rules", "gate": "human_approve", "auto": false, "input": "proposed_rules" },
    { "step": 5, "title": "Apply Rules", "skill": "evolution_engine", "auto": true, "input": "approved_rules" },
    { "step": 6, "title": "Report to Founder", "skill": "report_writer", "auto": true }
  ]
}
```

---

## 7. Security & Guardrails

### 7.1 Authentication
- **Azure Foundry:** System-Assigned Managed Identity (Entra ID). No API keys in `.env`.
- **Gmail:** App Password in `~/.hermes/.env` (chmod 600).
- **WhatsApp:** Session file in `~/.hermes/platforms/whatsapp/session/` (chmod 700).
- **Discord:** Bot token in `~/.hermes/.env`.
- **Git:** SSH deploy key with write access to ps3_labs_ai repo.

### 7.2 Access Control

| Resource | Who Can Access | How |
|---|---|---|
| VM SSH | Founder only | Azure AD auth + SSH key |
| Hermes Discord DM | Founder only | Discord user ID allowlist |
| Agent email inbox | Agent + Founder | Shared Gmail, app password |
| WhatsApp bot number | Agent only | Physical device not needed after pairing |
| CRM database | Agent + Founder | SQLite on VM disk |
| Beads DB | Agent + Founder | SQLite on VM disk |

### 7.3 Backup Strategy
- **Daily:** Git sync pushes `market_intel/`, `evolution_rules.json`, and CRM export to GitHub.
- **Weekly:** Azure Disk snapshot of the VM OS disk.
- **Beads:** `beads.db` is included in the Git sync (or copied to Azure Blob Storage).
- **WhatsApp session:** If lost, re-pair with `hermes whatsapp`. Session auto-saves to disk.

---

## 8. Cost Estimate (Monthly)

| Line Item | Amount | Notes |
|---|---|---|
| Azure VM (Standard B2ms, 24/7) | ~$45 | 2 vCPU, 8 GiB, Central India |
| Azure Disk (64 GB OS) | ~$5 | Standard HDD |
| Azure AI Foundry — Kimi K2.6 | ~$40–100 | Variable; ~$0.50-1/M input + $1.50-3/M output tokens |
| Network egress | ~$5–10 | Email + WhatsApp + API calls |
| WhatsApp number | $0–5 | Google Voice or prepaid SIM |
| Gmail | $0 | Free tier |
| **Total Estimated** | **$95–165 / month** | Kimi usage is the variable; everything else is fixed |

**Cost control:**
- Daily token usage logged to `usage_log.json`.
- Soft cap at $100/month: if exceeded, agent switches to shorter replies and batches more work.
- Founder alert via Discord if weekly spend >$25.

---

## 9. Implementation Roadmap

### Phase 1: VM + Hermes Foundation (Week 1)
- [ ] Provision Azure VM (Standard_B2ms, Ubuntu 24.04, Central India)
- [ ] Assign Managed Identity + `Azure AI User` role on Foundry resource
- [ ] SSH in, install Python 3.12, Node.js 20, Git
- [ ] Install Hermes Agent (`pip install hermes-agent`)
- [ ] Configure Hermes: `hermes model` → Azure Foundry → Kimi K2.6 → Entra ID
- [ ] Configure Email adapter (`hermes gateway setup`)
- [ ] Configure Discord adapter (bot token)
- [ ] Configure WhatsApp adapter (`hermes whatsapp`) — pair dedicated number
- [ ] Create systemd service for `hermes gateway`
- [ ] Test end-to-end: Discord → VM → Foundry → Discord reply

### Phase 2: Beads + CRM Foundation (Week 1–2)
- [ ] Initialize beads on VM: `bd init /opt/ps3labs/.beads`
- [ ] Create SQLite CRM schema
- [ ] Import `ahmedabad_b2b_leads.json` into CRM
- [ ] Write first beads formula: `outreach-sequence`
- [ ] Write first beads formula: `inbound-handler`
- [ ] Create `bd remember` entries for known lead preferences
- [ ] Test: `bd ready` → `bd create` → `bd close` cycle manually

### Phase 3: Skills + Personas (Week 2–3)
- [ ] Implement `crm_toolkit.py` (read/write/search)
- [ ] Implement `outreach_drafter.py` (personalized message generation)
- [ ] Implement `inbox_classifier.py` (intent classification)
- [ ] Implement `lead_enricher.py` (web research)
- [ ] Implement `follow_up_scheduler.py` (daily cron)
- [ ] Implement persona router (switch system prompt based on context)
- [ ] Test personas: Sales vs Marketing vs Research

### Phase 4: Evolution Engine (Week 3–4)
- [ ] Implement interaction logger (append to `interactions` table)
- [ ] Implement outcome tracker (link replies to original sends)
- [ ] Implement `pattern_extractor.py` (weekly analysis job)
- [ ] Implement `evolution_engine.py` (rule drafting + application)
- [ ] Create `evolution_rules.json` schema
- [ ] Wire founder feedback → immediate rule injection
- [ ] Test: send 20 test emails, run pattern extractor, verify rules created

### Phase 5: Workflows + Hardening (Week 4–5)
- [ ] Wire formulas to Hermes cron + event handlers
- [ ] Set up daily Git sync (cron at 2 AM)
- [ ] Configure Azure Disk snapshots (weekly)
- [ ] Set up cost tracking + Discord alerts
- [ ] Security review: chmods, allowlists, secret rotation
- [ ] Document disaster recovery: re-pair WhatsApp, restore from snapshot
- [ ] Founder onboarding session: how to use Discord to command the agent

---

## 10. Open Questions (Founder Decisions Required)

1. **Azure subscription & region:** Do you have an active Azure subscription? Which region — Central India (Pune) or somewhere else?
2. **Foundry resource name:** What is your Azure AI Foundry resource name / endpoint URL? (Needed for `base_url` in config.)
3. **Email domain:** Should we set up a custom domain (`sales@ps3labs.ai`) or use a dedicated Gmail for the agent?
4. **Human approval threshold:** Which actions should ALWAYS require your `/approve` before executing? (My default: >50 cold emails/day, WhatsApp to new numbers, any pricing quote, public content.)
5. **Discord integration:** Should the agent notify you in DMs or in the `#ps3labs` channel? DMs are more private; channel is more visible.
6. **Beads workflow:** Do you want to interact with beads directly (run `bd` commands yourself) or should the agent manage beads transparently and just report status to you?
7. **Existing lead lists:** Beyond `ahmedabad_b2b_leads.json`, do you have other lead sources to import? Should the agent self-discover new leads via web research?

---

## 11. Reference Architecture

```
AUTONOMOUS_DEV_TEAM.md  →  This Design  →  Implementation
         │                        │
         └─ Persona model ────────┘
         └─ Beads integration ────┘
         └─ Evolution engine ─────┘
         └- Event/cron routing ───┘
```

For a deeper understanding of the autonomous team paradigm (originally designed for coding but generalized here), see `AUTONOMOUS_DEV_TEAM.md` in this repository.

---

*Design v2.0 | PS3Labs | 2026-05-29*
