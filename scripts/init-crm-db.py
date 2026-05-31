#!/usr/bin/env python3
"""Initialize CRM database schema for outreach agent.

Run this on container startup before the gateway starts.
Creates all tables needed by the outreach skills.
"""

import os
import sqlite3
from pathlib import Path


def init_crm_db():
    db_path = Path(os.environ.get("HERMES_DIR", "/app/data")) / "crm.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Leads table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            company_name TEXT,
            contact_name TEXT,
            email TEXT,
            phone TEXT,
            industry TEXT,
            source TEXT DEFAULT 'outbound',
            status TEXT DEFAULT 'new',
            priority INTEGER DEFAULT 2,
            notes TEXT,
            assigned_persona TEXT,
            last_contact TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Interactions table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS interactions (
            id TEXT PRIMARY KEY,
            lead_id TEXT,
            channel TEXT,
            direction TEXT,
            message_type TEXT,
            content_preview TEXT,
            template_id TEXT,
            sentiment TEXT DEFAULT 'neutral',
            outcome TEXT DEFAULT 'pending',
            evolution_rule_applied TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
        """
    )

    # Pending actions table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_actions (
            id TEXT PRIMARY KEY,
            action_type TEXT,
            description TEXT,
            payload TEXT,
            urgency INTEGER DEFAULT 2,
            status TEXT DEFAULT 'pending',
            approved_by TEXT,
            approved_at TEXT,
            rejected_reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Evolution rules table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS evolution_rules (
            id TEXT PRIMARY KEY,
            source TEXT,
            confidence REAL,
            condition TEXT,
            action TEXT,
            priority TEXT DEFAULT 'medium',
            active INTEGER DEFAULT 1,
            hit_count INTEGER DEFAULT 0,
            expires_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Cost tracking table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cost_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT,
            tokens_input INTEGER,
            tokens_output INTEGER,
            cost_usd REAL,
            task_type TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Monthly cost summary view
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monthly_cost (
            month TEXT PRIMARY KEY,
            total_cost REAL DEFAULT 0.0
        )
        """
    )

    # Pipeline summary view
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS lead_pipeline (
            status TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0
        )
        """
    )

    # Seed pipeline statuses
    for status in ['new', 'contacted', 'engaged', 'meeting', 'proposal', 'closed_won', 'closed_lost', 'nurture']:
        cursor.execute(
            "INSERT OR IGNORE INTO lead_pipeline (status, count) VALUES (?, 0)",
            (status,)
        )

    conn.commit()
    conn.close()
    print(f"[init-crm-db] Database initialized at {db_path}")


if __name__ == "__main__":
    init_crm_db()
