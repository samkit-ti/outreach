"""PS3Labs CRM Toolkit — Core database operations for the Hermes agent."""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("HERMES_DIR", "/opt/hermes-agent")) / "crm.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def generate_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# LEADS
# ---------------------------------------------------------------------------

def create_lead(
    company_name: str = "",
    contact_name: str = "",
    email: str = "",
    phone: str = "",
    industry: str = "",
    source: str = "outbound",
    status: str = "new",
    priority: int = 2,
    notes: str = "",
) -> dict[str, Any]:
    lead_id = generate_id("ld-")
    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO leads (id, company_name, contact_name, email, phone,
                               industry, source, status, priority, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (lead_id, company_name, contact_name, email, phone,
             industry, source, status, priority, notes),
        )
        conn.commit()
    return get_lead(lead_id)


def get_lead(lead_id: str) -> dict[str, Any] | None:
    with _get_db() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else None


def get_lead_by_email(email: str) -> dict[str, Any] | None:
    with _get_db() as conn:
        row = conn.execute("SELECT * FROM leads WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def update_lead(lead_id: str, **fields) -> dict[str, Any]:
    allowed = {"company_name", "contact_name", "email", "phone", "industry",
               "source", "status", "priority", "notes", "assigned_persona", "last_contact"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_lead(lead_id) or {}
    updates["updated_at"] = datetime.utcnow().isoformat()
    with _get_db() as conn:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [lead_id]
        conn.execute(f"UPDATE leads SET {set_clause} WHERE id = ?", values)
        conn.commit()
    return get_lead(lead_id) or {}


def list_leads(
    status: str | None = None,
    industry: str | None = None,
    min_priority: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conditions = []
    params = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if industry:
        conditions.append("industry = ?")
        params.append(industry)
    if min_priority is not None:
        conditions.append("priority <= ?")
        params.append(min_priority)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with _get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM leads {where} ORDER BY priority, created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# INTERACTIONS
# ---------------------------------------------------------------------------

def log_interaction(
    lead_id: str,
    channel: str,
    direction: str,
    message_type: str,
    content_preview: str = "",
    template_id: str = "",
    sentiment: str = "neutral",
    outcome: str = "pending",
    evolution_rule_applied: str = "",
) -> dict[str, Any]:
    interaction_id = generate_id("in-")
    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO interactions (id, lead_id, channel, direction, message_type,
                                      content_preview, template_id, sentiment, outcome,
                                      evolution_rule_applied)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (interaction_id, lead_id, channel, direction, message_type,
             content_preview, template_id, sentiment, outcome, evolution_rule_applied),
        )
        conn.commit()
    return {"id": interaction_id, "lead_id": lead_id, "status": "logged"}


def get_interactions(lead_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM interactions WHERE lead_id = ? ORDER BY timestamp DESC LIMIT ?",
            (lead_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def update_interaction_outcome(interaction_id: str, outcome: str) -> None:
    with _get_db() as conn:
        conn.execute(
            "UPDATE interactions SET outcome = ? WHERE id = ?",
            (outcome, interaction_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# PENDING ACTIONS
# ---------------------------------------------------------------------------

def queue_action(
    action_type: str,
    description: str,
    payload: dict,
    urgency: int = 2,
) -> dict[str, Any]:
    action_id = generate_id("pa-")
    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO pending_actions (id, action_type, description, payload, urgency)
            VALUES (?, ?, ?, ?, ?)
            """,
            (action_id, action_type, description, json.dumps(payload), urgency),
        )
        conn.commit()
    return {"id": action_id, "status": "pending", "description": description}


def list_pending_actions(limit: int = 50) -> list[dict[str, Any]]:
    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM pending_actions
            WHERE status = 'pending' ORDER BY urgency, created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def approve_action(action_id: str, approved_by: str) -> dict[str, Any]:
    with _get_db() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
            (approved_by, datetime.utcnow().isoformat(), action_id),
        )
        conn.commit()
    return {"id": action_id, "status": "approved"}


def reject_action(action_id: str, reason: str) -> dict[str, Any]:
    with _get_db() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = 'rejected', rejected_reason = ? WHERE id = ?",
            (reason, action_id),
        )
        conn.commit()
    return {"id": action_id, "status": "rejected"}


# ---------------------------------------------------------------------------
# EVOLUTION RULES
# ---------------------------------------------------------------------------

def create_rule(
    source: str,
    confidence: float,
    condition: str,
    action: str,
    priority: str = "medium",
    expires_days: int = 90,
) -> dict[str, Any]:
    rule_id = generate_id("evr-")
    expires_at = (datetime.utcnow() + timedelta(days=expires_days)).isoformat()
    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO evolution_rules (id, source, confidence, condition, action, priority, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rule_id, source, confidence, condition, action, priority, expires_at),
        )
        conn.commit()
    return {"id": rule_id, "status": "created"}


def get_active_rules() -> list[dict[str, Any]]:
    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM evolution_rules
            WHERE active = 1 AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY priority DESC, created_at DESC
            """,
            (datetime.utcnow().isoformat(),),
        ).fetchall()
        return [dict(r) for r in rows]


def increment_rule_hit(rule_id: str) -> None:
    with _get_db() as conn:
        conn.execute(
            "UPDATE evolution_rules SET hit_count = hit_count + 1 WHERE id = ?",
            (rule_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# COST TRACKING
# ---------------------------------------------------------------------------

def log_cost(model: str, tokens_input: int, tokens_output: int, cost_usd: float, task_type: str) -> None:
    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO cost_log (model, tokens_input, tokens_output, cost_usd, task_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (model, tokens_input, tokens_output, cost_usd, task_type),
        )
        conn.commit()


def get_monthly_cost() -> float:
    with _get_db() as conn:
        row = conn.execute(
            "SELECT total_cost FROM monthly_cost ORDER BY month DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else 0.0


# ---------------------------------------------------------------------------
# FOLLOW-UP QUERIES
# ---------------------------------------------------------------------------

def get_stale_leads(days: int = 5, limit: int = 50) -> list[dict[str, Any]]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            WHERE (last_contact IS NULL OR last_contact < ?)
              AND status NOT IN ('closed_won', 'closed_lost', 'nurture')
            ORDER BY priority, created_at DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pipeline_summary() -> dict[str, int]:
    with _get_db() as conn:
        rows = conn.execute("SELECT status, count FROM lead_pipeline").fetchall()
        return {r[0]: r[1] for r in rows}
