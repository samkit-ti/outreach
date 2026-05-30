#!/usr/bin/env python3
"""Import existing leads from ps3_labs_ai JSON files into CRM."""

import json
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, "/opt/hermes-agent/skills")
from crm_toolkit import create_lead


def import_from_json(filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found: {filepath}")
        return {"status": "error", "reason": "file_not_found"}

    with open(path) as f:
        data = json.load(f)

    # Handle both list and dict-with-keys formats
    leads = data if isinstance(data, list) else data.get("leads", [])

    imported = 0
    skipped = 0

    for entry in leads:
        try:
            create_lead(
                company_name=entry.get("company", entry.get("company_name", "")),
                contact_name=entry.get("contact", entry.get("contact_name", "")),
                email=entry.get("email", ""),
                phone=entry.get("phone", ""),
                industry=entry.get("industry", "general"),
                source=entry.get("source", "import"),
                status="new",
                priority=entry.get("priority", 2),
                notes=entry.get("notes", ""),
            )
            imported += 1
        except Exception as e:
            print(f"Skip: {entry.get('email', 'unknown')} — {e}")
            skipped += 1

    return {
        "status": "success",
        "imported": imported,
        "skipped": skipped,
        "source": filepath,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: import_leads.py <path-to-leads.json>")
        sys.exit(1)
    result = import_from_json(sys.argv[1])
    print(json.dumps(result, indent=2))
