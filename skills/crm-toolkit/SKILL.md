---
name: crm-toolkit
description: "Core CRM operations: leads, interactions, actions, and pipeline tracking"
version: 1.0.0
author: PS3Labs
license: MIT
metadata:
  hermes:
    tags: [sales, crm, database, leads, pipeline]
    related_skills: [lead-enricher, outreach-drafter, follow-up-scheduler]
    requires_env:
      - HERMES_DIR
---

# CRM Toolkit

Core database layer for the outreach agent. Manages leads, interactions, pending actions, and pipeline analytics.

## Database

SQLite at `${HERMES_DIR}/crm.db`

Tables:
- `leads` — Lead records
- `interactions` — Message history
- `pending_actions` — Queued follow-ups awaiting approval/auto-send
- `evolution_rules` — Learned patterns from successful outreach
- `cost_log` — LLM cost tracking

## Commands

### Lead Management
- `/add-lead <email> [company] [name] [industry]` — Add a new lead
- `/get-lead <lead-id>` — View lead details
- `/update-lead <lead-id> <field> <value>` — Update lead field
- `/list-leads [status] [industry]` — List leads with filters

### Interaction Tracking
- `/log-interaction <lead-id> <channel> <direction> <message>` — Log a message
- `/get-interactions <lead-id>` — View conversation history

### Actions
- `/queue-action <type> <description>` — Queue a follow-up action
- `/pending-actions` — List pending actions
- `/approve-action <action-id>` — Approve an action
- `/reject-action <action-id> <reason>` — Reject an action

### Pipeline
- `/pipeline` — Show pipeline summary
- `/stale-leads [days]` — Find leads with no recent contact

## Lead Statuses

| Status | Meaning |
|--------|---------|
| new | Just added, no outreach yet |
| contacted | First message sent |
| engaged | Lead replied or showed interest |
| meeting | Meeting/demo scheduled |
| proposal | Proposal sent |
| closed_won | Deal won |
| closed_lost | Deal lost |
| nurture | Long-term nurture |

## Example

```
/add-lead info@zydushospitals.com "Zydus Hospital" "Dr. Shah" healthcare
/get-lead ld-abc123
/update-lead ld-abc123 status engaged
/pipeline
```
