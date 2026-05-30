"""PS3Labs Evolution Engine — Applies and manages self-modifying behavior rules.

This is a thin orchestration layer around the evolution_rules database.
The heavy lifting (pattern extraction, rule drafting) happens in pattern_extractor.py.
"""

import json
from datetime import datetime


def apply_rules(rule_ids: list[str]) -> list[dict]:
    """Activate a set of proposed evolution rules.

    Args:
        rule_ids: List of evolution_rule IDs to activate

    Returns:
        List of activation results
    """
    try:
        from .crm_toolkit import _get_db
    except ImportError:
        import sys
        sys.path.insert(0, "/opt/hermes-agent/skills")
        from crm_toolkit import _get_db

    results = []
    with _get_db() as conn:
        for rid in rule_ids:
            conn.execute(
                "UPDATE evolution_rules SET active = 1 WHERE id = ?",
                (rid,),
            )
            results.append({"rule_id": rid, "status": "activated"})
        conn.commit()
    return results


def deactivate_rule(rule_id: str) -> dict:
    """Deactivate a rule (e.g., after founder rejection)."""
    try:
        from .crm_toolkit import _get_db
    except ImportError:
        import sys
        sys.path.insert(0, "/opt/hermes-agent/skills")
        from crm_toolkit import _get_db

    with _get_db() as conn:
        conn.execute(
            "UPDATE evolution_rules SET active = 0 WHERE id = ?",
            (rule_id,),
        )
        conn.commit()
    return {"rule_id": rule_id, "status": "deactivated"}


def get_rules_for_prompt() -> str:
    """Fetch active rules formatted for injection into an LLM system prompt.

    Returns a markdown-formatted string of active rules.
    """
    try:
        from .crm_toolkit import get_active_rules
    except ImportError:
        import sys
        sys.path.insert(0, "/opt/hermes-agent/skills")
        from crm_toolkit import get_active_rules

    rules = get_active_rules()
    if not rules:
        return ""

    lines = ["## Active Evolution Rules", ""]
    for r in rules:
        lines.append(f"- **{r['priority'].upper()}** | {r['condition']} → {r['action']}")
        lines.append(f"  (confidence: {r['confidence']:.0%}, hits: {r['hit_count']})")
    lines.append("")
    return "\n".join(lines)


def founder_feedback_to_rule(feedback: str, context: dict) -> dict:
    """Convert founder feedback into an immediate evolution rule.

    This is the highest-priority signal. Called directly when the founder
    gives feedback via Discord or email.
    """
    try:
        from .crm_toolkit import create_rule
    except ImportError:
        import sys
        sys.path.insert(0, "/opt/hermes-agent/skills")
        from crm_toolkit import create_rule

    rule = create_rule(
        source="founder_feedback",
        confidence=1.0,  # Founder feedback is gospel
        condition=f"Context: {json.dumps(context)}",
        action=feedback,
        priority="critical",
        expires_days=365,
    )
    return rule


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(get_rules_for_prompt())
