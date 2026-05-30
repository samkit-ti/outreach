# AUTONOMOUS_DEV_TEAM.md — Reference Architecture

## What This Is

A reference architecture for an autonomous agent "team" that handles a business function end-to-end. Originally designed for software development, generalized here for any domain (sales, marketing, support, operations). The core idea: a single daemon running Hermes Agent orchestrates multiple **personas** or **modes**, each with specific skills, memory, and workflows. All work is tracked in **beads** (issues, tasks, formulas, memories). The system evolves through feedback loops.

## Core Philosophy

1. **Agents are not chatbots — they are employees.** They have roles, responsibilities, and memory.
2. **All work is tracked.** Every task, bug, feature, or research item lives in beads. The agent creates, claims, and closes issues just like a human team member.
3. **Memory is persistent and structured.** Short-term (session context), mid-term (beads memories, daily logs), long-term (curated wisdom in MEMORY.md / SOUL.md equivalents).
4. **The system evolves.** Every client interaction, founder feedback, success, and failure feeds back into the agent's behavior via a structured feedback loop.
5. **Human-in-the-loop when stakes are high.** The agent operates autonomously within guardrails. High-stakes actions (contracts, pricing, client commitments) require explicit approval.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AZURE VM (Persistent)                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           HERMES GATEWAY (Single Daemon)              │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │  │
│  │  │   Sales      │  │  Marketing   │  │  Research   │ │  │
│  │  │   Persona    │  │   Persona    │  │   Persona   │ │  │
│  │  │  (outreach,  │  │  (content,   │  │  (market    │ │  │
│  │  │   CRM,       │  │   campaigns, │  │   intel,    │ │  │
│  │  │   follow-up) │  │   analytics) │  │   leads)    │ │  │
│  │  └──────────────┘  └──────────────┘  └─────────────┘ │  │
│  │              ┌──────────────────┐                     │  │
│  │              │  Shared Memory   │                     │  │
│  │              │  & Context       │                     │  │
│  │              └──────────────────┘                     │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              BEADS (Task & Memory Layer)              │  │
│  │  • Issues: open/closed/in_progress                    │  │
│  │  • Formulas: reusable workflows (bd mol pour)         │  │
│  │  • Memories: persistent knowledge (bd remember)       │  │
│  │  • Dependencies: task blocking/ordering               │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │            FEEDBACK & EVOLUTION ENGINE                │  │
│  │  • Interaction Logger (every client touchpoint)       │  │
│  │  • Outcome Tracker (reply rate, conversion, sentiment)│  │
│  │  • Pattern Extractor (what worked vs failed)          │  │
│  │  • Self-Modifier (updates prompts, templates, rules)  │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                           │
    ┌────▼────┐                 ┌────▼────┐
    │  EMAIL  │                 │ WHATSAPP │
    │ (IMAP/  │                 │ (Baileys │
    │  SMTP)  │                 │ bridge)  │
    └─────────┘                 └─────────┘
```

## Persona Design

Each persona is a **mode switch** within the same Hermes agent, not a separate process. Think of it as a senior generalist who can put on different hats.

### Persona: Sales

**Role:** Owns the revenue pipeline.
**Skills:**
- CRM toolkit (read/write leads, update statuses, track touchpoints)
- Outreach drafter (personalized cold emails, WhatsApp messages)
- Follow-up scheduler (identify stale leads, draft nudges)
- Inbox classifier (hot lead / inquiry / junk / partner / competitor)
- Objection handler (prepare responses to common objections)

**Guardrails:**
- Never send a message without logging it to CRM.
- Cold outreach >50/day requires human approval.
- Pricing or contract terms are suggestion-only; human approves.

### Persona: Marketing

**Role:** Owns awareness, content, and positioning.
**Skills:**
- Market research (competitor tracking, industry news, opportunities)
- Content generator (LinkedIn posts, blog outlines, case studies)
- Campaign analyst (track what content drives leads)
- SEO / keyword tracker (monitor target terms, suggest content)
- Event / webinar coordinator (identify relevant events, draft outreach)

**Guardrails:**
- All public content requires human approval before publishing.
- Brand voice guidelines are immutable unless founder explicitly updates them.

### Persona: Research

**Role:** Intelligence gathering and lead discovery.
**Skills:**
- Lead enricher (web research to fill missing company/person data)
- Opportunity scout (monitor job postings, funding news, RFPs)
- ICP matcher (score leads against ideal customer profile)
- Trend analyzer (emerging tech, regulatory changes, market shifts)

**Guardrails:**
- Respect robots.txt and rate limits.
- No scraping behind paywalls or restricted content.

## Beads Integration

### Task Lifecycle

```
Discovery → Create (bd create) → Queue → Claim (bd update --claim) →
Execute → Verify → Close (bd close) → Archive → Learn
```

### Formulas (Reusable Workflows)

Beads formulas (`bd mol pour`) define structured multi-step workflows. Examples:

**`outreach-sequence.formula.json`**
```json
{
  "name": "outreach-sequence",
  "steps": [
    { "step": 1, "title": "Enrich lead", "skill": "lead_enricher", "auto": true },
    { "step": 2, "title": "Draft personalized outreach", "skill": "outreach_drafter", "auto": true },
    { "step": 3, "title": "Human review", "gate": "human_approve", "auto": false },
    { "step": 4, "title": "Send message", "skill": "send_message", "auto": true },
    { "step": 5, "title": "Log to CRM", "skill": "crm_log", "auto": true },
    { "step": 6, "title": "Schedule follow-up", "skill": "follow_up_scheduler", "auto": true }
  ]
}
```

**`weekly-market-scan.formula.json`**
```json
{
  "name": "weekly-market-scan",
  "steps": [
    { "step": 1, "title": "Search competitor news", "skill": "web_search", "auto": true },
    { "step": 2, "title": "Search industry RFPs", "skill": "web_search", "auto": true },
    { "step": 3, "title": "Analyze trends", "skill": "trend_analyzer", "auto": true },
    { "step": 4, "title": "Draft report", "skill": "report_writer", "auto": true },
    { "step": 5, "title": "Send to founder", "skill": "email_send", "auto": true }
  ]
}
```

### Memory Architecture

```
Layer 0: Session Context (in-memory, per conversation)
Layer 1: Beads Daily Log (memory/YYYY-MM-DD.md — raw events)
Layer 2: Beads Persistent Memory (bd remember — key facts)
Layer 3: Curated Long-Term (MEMORY.md — distilled wisdom)
Layer 4: Evolution Rules (evolution_rules.json — *learned* behavior modifications)
```

**`bd remember` usage:**
- "Lead X at Apollo Hospitals prefers WhatsApp over email"
- "Pricing objection about ₹15K tier is common; counter with ROI calculator"
- "Founder prefers casual tone, no exclamation marks in cold outreach"
- "Template v3 had 12% reply rate; v2 had 8% — v3 is better"

## The Evolution Engine (Feedback Loop)

This is the secret sauce that makes the system "highly evolving."

### 1. Interaction Logger

Every client touchpoint is logged as a structured event:

```json
{
  "timestamp": "2026-05-29T09:30:00Z",
  "lead_id": "apollo-ahmedabad-01",
  "channel": "email",
  "direction": "inbound",
  "message_type": " pricing_objection",
  "sentiment": "neutral",
  "agent_action": "sent_pricing_pdf",
  "outcome": "pending"
}
```

### 2. Outcome Tracker

As interactions resolve, outcomes are attached:

```json
{
  "interaction_id": "abc123",
  "resolution": "positive_reply",  // or "no_reply", "unsubscribe", "meeting_booked", "closed_won"
  "time_to_reply_hours": 48,
  "final_value_inr": 450000,
  "attributed_strategy": "template_v3_healthcare_roi"
}
```

### 3. Pattern Extractor (Weekly / Triggered)

A periodic job (or triggered analysis) scans recent interactions:

```python
# Conceptual
patterns = analyze_interactions(window="7d")
# Returns:
# - "Template v3 outperforms v2 by 4pp on healthcare leads"
# - "WhatsApp follow-ups get 2x reply rate vs email for <₹1L deals"
# - "Leads from LinkedIn inbound convert 3x better than cold outbound"
# - "Objection about DPDP compliance is rising; need new response"
```

### 4. Self-Modifier

Extracted patterns are converted into **evolution rules** that modify agent behavior:

```json
{
  "rule_id": "evr-026",
  "created_at": "2026-05-29",
  "source": "pattern_extractor_7d",
  "confidence": 0.85,
  "condition": "lead.industry == 'healthcare' AND deal_value < 100000",
  "action": "prefer_whatsapp_over_email",
  "priority": "high",
  "expires_at": "2026-08-29"
}
```

Rules are injected into the system prompt context. Over time, the agent becomes "smarter" without code changes.

### 5. Human Override

Founder feedback is the highest-priority signal:

```
Founder: "That email was too aggressive. Tone it down for education leads."
→ Pattern Extractor creates rule: "education_leads.tone = 'soft_persuasive'"
→ Self-Modifier updates persona prompt for Education ICP
→ Agent behavior changes immediately
```

## Event-Driven vs Cron-Driven

| Trigger Type | Example | Handler |
|---|---|---|
| **Inbound Event** | New email from lead | Inbox classifier → CRM update → auto-reply or queue for human |
| **Inbound Event** | WhatsApp message | Lead lookup → context load → draft reply |
| **Cron Schedule** | Daily 9 AM | Follow-up scheduler scans stale leads, drafts nudges |
| **Cron Schedule** | Weekly Monday 10 AM | Market research scan, competitor digest |
| **State Change** | Lead status → "hot" | Trigger outreach sequence formula |
| **Founder Command** | "Research Apollo Hospitals" | Spawn background research task, report back |
| **External Event** | Competitor pricing change | Trigger alert to founder + update battlecards |

## Guardrails for Autonomy

| Action | Autonomy Level | Approval Required |
|---|---|---|
| Log interaction to CRM | Full auto | No |
| Draft outreach message | Full auto | No |
| Send cold email (<50/day) | Full auto | No |
| Send cold email (>50/day) | Governed | Yes (human) |
| Send WhatsApp to new number | Governed | Yes (human) |
| Publish content publicly | Governed | Yes (human) |
| Quote pricing | Governed | Yes (human suggestion) |
| Sign contract / NDA | Blocked | Yes (human only) |
| Delete/modify CRM record | Governed | Yes (human) |
| Update evolution rules | Governed | Yes (human review weekly) |

## Implementation Checklist

- [ ] Azure VM provisioned, Hermes installed, systemd service configured
- [ ] Azure AI Foundry endpoint configured (Kimi K2.6)
- [ ] Beads initialized (`bd init`) on VM with persistent volume
- [ ] Email adapter configured (Gmail app password)
- [ ] WhatsApp bridge paired (dedicated number)
- [ ] CRM schema defined (SQLite or JSONL on persistent disk)
- [ ] Persona system prompts written (Sales, Marketing, Research)
- [ ] Interaction logger implemented (append to JSONL)
- [ ] Outcome tracker linked to CRM state transitions
- [ ] Pattern extractor cron job configured (weekly)
- [ ] Self-modifier reads/writes `evolution_rules.json`
- [ ] Human approval queue implemented (pending_actions table)
- [ ] Foundation inbound lead lists imported
- [ ] At least one beads formula defined and tested
- [ ] First `bd remember` entry created

---

*Reference v1.0 | Adapted from coding-autonomous-team pattern | For PS3Labs Sales/Marketing Agent*
