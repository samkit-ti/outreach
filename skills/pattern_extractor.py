"""PS3Labs Pattern Extractor — Weekly cron job for the Evolution Engine.

Analyzes last week's interactions, extracts patterns, and drafts evolution rules.
"""

import json
from datetime import datetime, timedelta


def run_weekly_pattern_extraction() -> dict:
    """Main entry point for the weekly pattern extraction cron.

    Returns extracted patterns and proposed rules.
    """
    try:
        from .crm_toolkit import _get_db, create_rule, log_cost
    except ImportError:
        import sys
        sys.path.insert(0, "/opt/hermes-agent/skills")
        from crm_toolkit import _get_db, create_rule, log_cost

    # Fetch last week's interactions
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()

    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT channel, message_type, outcome, sentiment, template_id, industry
            FROM interactions
            WHERE timestamp > ?
            """,
            (week_ago,),
        ).fetchall()

    if not rows:
        return {"status": "no_data", "reason": "No interactions in last 7 days", "patterns": []}

    # Build summary stats
    stats = {
        "total_interactions": len(rows),
        "by_channel": {},
        "by_outcome": {},
        "by_template": {},
        "by_industry": {},
    }

    for r in rows:
        for key in ("channel", "outcome", "template_id", "industry"):
            val = r[key] or "unknown"
            container = stats[f"by_{key}"]
            container[val] = container.get(val, 0) + 1

    # Calculate reply rates by channel
    reply_rates = {}
    for channel, total in stats["by_channel"].items():
        replies = sum(1 for r in rows if r["channel"] == channel and r["outcome"] in ("replied", "meeting_booked", "closed_won"))
        reply_rates[channel] = round(replies / total, 2) if total > 0 else 0

    # Calculate template performance
    template_perf = {}
    for tmpl, total in stats["by_template"].items():
        replies = sum(1 for r in rows if r["template_id"] == tmpl and r["outcome"] in ("replied", "meeting_booked"))
        template_perf[tmpl] = round(replies / total, 2) if total > 0 else 0

    # Build the analysis prompt for the LLM
    prompt = f"""You are a data analyst reviewing a sales team's performance.

WEEKLY STATS:
{json.dumps(stats, indent=2)}

REPLY RATES BY CHANNEL:
{json.dumps(reply_rates, indent=2)}

TEMPLATE PERFORMANCE:
{json.dumps(template_perf, indent=2)}

TASK:
1. Identify the top 3 patterns that explain why some interactions succeeded and others failed.
2. Propose 3 actionable behavioral rules for the sales agent.
3. Flag any anomalies or concerns.

For each proposed rule, provide:
- Condition (when to apply)
- Action (what to do)
- Confidence (0.0-1.0)
- Priority (low/medium/high)

OUTPUT JSON:
{{
  "patterns": [
    {{
      "observation": "what you noticed",
      "evidence": "supporting data",
      "confidence": 0.85
    }}
  ],
  "proposed_rules": [
    {{
      "condition": "when this applies",
      "action": "what to do",
      "confidence": 0.85,
      "priority": "high"
    }}
  ],
  "anomalies": ["anything concerning"],
  "summary": "one paragraph summary for the founder"
}}
"""

    # In production, this prompt is sent to Kimi K2.6.
    # The response JSON is parsed, and proposed_rules are inserted into the DB.
    # For now, return the prompt structure.

    return {
        "status": "analysis_ready",
        "stats": stats,
        "reply_rates": reply_rates,
        "template_perf": template_perf,
        "prompt": prompt,
        "week_start": week_ago,
        "run_at": datetime.utcnow().isoformat(),
    }


def apply_proposed_rules(proposed_rules: list[dict]) -> list[dict]:
    """Insert proposed rules into the evolution_rules table.

    In the full flow, the LLM output is reviewed by the founder before calling this.
    """
    try:
        from .crm_toolkit import create_rule
    except ImportError:
        import sys
        sys.path.insert(0, "/opt/hermes-agent/skills")
        from crm_toolkit import create_rule

    created = []
    for rule in proposed_rules:
        result = create_rule(
            source="pattern_extractor",
            confidence=rule.get("confidence", 0.5),
            condition=rule.get("condition", ""),
            action=rule.get("action", ""),
            priority=rule.get("priority", "medium"),
        )
        created.append(result)
    return created


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = run_weekly_pattern_extraction()
    print(json.dumps(result, indent=2, default=str))
