---
name: follow-up-scheduler
description: "Daily cron job to identify stale leads and queue follow-up actions"
version: 1.0.0
author: PS3Labs
license: MIT
metadata:
  hermes:
    tags: [sales, cron, follow-up, scheduling, automation]
    related_skills: [outreach-drafter, crm-toolkit, lead-enricher]
    requires_env:
      - HERMES_DIR
    cron:
      schedule: "0 9 * * *"
      command: "python -m skills.follow_up_scheduler"
---

# Follow-Up Scheduler

Daily automation that scans the CRM for stale leads (no contact in 5+ days) and queues appropriate follow-up actions.

## When It Runs

- Daily at 09:00 UTC (configurable)
- Triggered by Hermes cron system
- Can also run manually via `/run-follow-ups`

## Logic

For each stale lead, determine:

1. **Status-based message type**:
   - `new` → cold_outreach (email)
   - `contacted/engaged` → follow_up (WhatsApp for healthcare, email otherwise)
   - `meeting` → follow_up (formal email)
   - `proposal` → follow_up (formal email)

2. **Channel selection**:
   - High-stakes (proposal/meeting) → email + approval queue
   - Low-stakes (new/contacted) → auto-send via preferred channel

3. **Queue action**:
   - Add to `pending_actions` table
   - Log interaction in `interactions` table
   - Mark as "pending" outcome

## Commands

- `/run-follow-ups` — Manually trigger the scheduler
- `/pending-actions` — List all queued follow-ups
- `/approve-action <action-id>` — Approve a high-stakes follow-up

## Output

Returns a summary:
```json
{
  "status": "success",
  "queued": 12,
  "skipped": 3,
  "total_stale": 15,
  "actions": [...]
}
```

## Auto-Send Guardrails

- Max 1 auto-follow-up per lead per 3 days
- No auto-send for leads marked "do_not_contact"
- Respect timezone (send during business hours 9 AM - 6 PM IST)
- Skip on weekends unless explicitly configured
