"""PS3Labs Follow-Up Scheduler — Daily cron job to identify and queue follow-ups."""

import json
from datetime import datetime, timedelta


def run_daily_follow_up() -> dict:
    """Main entry point for the daily follow-up cron job.

    Returns a summary of actions taken.
    """
    try:
        from .crm_toolkit import get_stale_leads, queue_action, log_interaction
        from .outreach_drafter import draft_email, draft_whatsapp
    except ImportError:
        import sys
        sys.path.insert(0, "/opt/hermes-agent/skills")
        from crm_toolkit import get_stale_leads, queue_action, log_interaction
        from outreach_drafter import draft_email, draft_whatsapp

    stale_leads = get_stale_leads(days=5, limit=50)

    if not stale_leads:
        return {"status": "no_action", "reason": "No stale leads found", "queued": 0}

    queued_count = 0
    skipped_count = 0
    actions = []

    for lead in stale_leads:
        lead_id = lead["id"]
        industry = lead.get("industry", "general")
        status = lead.get("status", "new")
        last_contact = lead.get("last_contact")

        # Determine follow-up strategy based on status and recency
        if status == "new":
            message_type = "cold_outreach"
            channel = "email"
        elif status in ("contacted", "engaged"):
            message_type = "follow_up"
            # Prefer WhatsApp for healthcare under ₹1L deal size (evolution rule placeholder)
            channel = "whatsapp" if industry == "healthcare" else "email"
        elif status == "meeting":
            message_type = "follow_up"
            channel = "email"  # Post-meeting follow-ups should be formal
        elif status == "proposal":
            message_type = "follow_up"
            channel = "email"
        else:
            skipped_count += 1
            continue

        # Draft the message
        if channel == "email":
            draft = draft_email(lead, message_type=message_type)
        else:
            draft = draft_whatsapp(lead, message_type=message_type)

        # Queue for approval if high-stakes
        if status in ("proposal", "meeting"):
            action = queue_action(
                action_type=f"{channel}_follow_up",
                description=f"Follow-up to {lead.get('company_name', 'Lead')} ({status})",
                payload={
                    "lead_id": lead_id,
                    "channel": channel,
                    "message_type": message_type,
                    "draft_prompt": draft["prompt"],
                    "template_id": draft["template_id"],
                },
                urgency=1 if status == "proposal" else 2,
            )
        else:
            # Lower-stakes leads: log the intent but auto-send within guardrails
            action = {
                "id": "auto-" + lead_id,
                "status": "auto_queued",
                "description": f"Auto follow-up to {lead.get('company_name', 'Lead')}",
            }

        # Log the scheduled interaction
        log_interaction(
            lead_id=lead_id,
            channel=channel,
            direction="outbound",
            message_type=message_type,
            content_preview=f"[scheduled] {action['description']}",
            template_id=draft["template_id"],
            outcome="pending",
        )

        actions.append({
            "lead_id": lead_id,
            "company": lead.get("company_name"),
            "channel": channel,
            "type": message_type,
            "action_id": action.get("id"),
            "action_status": action.get("status"),
        })
        queued_count += 1

    return {
        "status": "success",
        "queued": queued_count,
        "skipped": skipped_count,
        "total_stale": len(stale_leads),
        "actions": actions,
        "run_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = run_daily_follow_up()
    print(json.dumps(result, indent=2, default=str))
