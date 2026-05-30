"""Tests for the CRM toolkit."""

import pytest
import sqlite3
from pathlib import Path
from unittest.mock import patch

# Ensure skills are importable
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "skills"))

from crm_toolkit import (
    generate_id,
    create_lead,
    get_lead,
    update_lead,
    list_leads,
    log_interaction,
    queue_action,
    get_stale_leads,
)


@pytest.fixture
def mock_db(tmp_path, monkeypatch):
    """Use a temporary database for tests."""
    db_file = tmp_path / "test_crm.db"
    monkeypatch.setattr("crm_toolkit.DB_PATH", db_file)
    
    # Init schema
    schema = Path(__file__).parent.parent / "sql" / "init_schema.sql"
    conn = sqlite3.connect(db_file)
    conn.executescript(schema.read_text())
    conn.close()
    
    return db_file


class TestLeadManagement:
    """Test lead CRUD operations."""

    def test_generate_id(self):
        """ID generation should produce unique strings."""
        id1 = generate_id("ld-")
        id2 = generate_id("ld-")
        assert id1.startswith("ld-")
        assert id2.startswith("ld-")
        assert id1 != id2
        assert len(id1) == 15  # prefix + 12 hex chars

    def test_create_and_get_lead(self, mock_db):
        """Should create a lead and retrieve it."""
        lead = create_lead(
            company_name="Test Corp",
            contact_name="Alice",
            email="alice@test.com",
            industry="healthcare",
            priority=1,
        )
        
        assert lead["company_name"] == "Test Corp"
        assert lead["contact_name"] == "Alice"
        assert lead["email"] == "alice@test.com"
        assert lead["industry"] == "healthcare"
        assert lead["status"] == "new"
        
        # Retrieve
        fetched = get_lead(lead["id"])
        assert fetched is not None
        assert fetched["email"] == "alice@test.com"

    def test_get_lead_by_email(self, mock_db):
        """Should find lead by email."""
        create_lead(email="unique@test.com", company_name="Unique")
        
        lead = get_lead_by_email("unique@test.com")
        assert lead is not None
        assert lead["company_name"] == "Unique"
        
        assert get_lead_by_email("notfound@test.com") is None

    def test_update_lead(self, mock_db):
        """Should update lead fields."""
        lead = create_lead(company_name="Old Name")
        
        updated = update_lead(lead["id"], company_name="New Name", status="contacted")
        assert updated["company_name"] == "New Name"
        assert updated["status"] == "contacted"

    def test_list_leads_by_status(self, mock_db):
        """Should filter leads by status."""
        create_lead(company_name="A", status="new")
        create_lead(company_name="B", status="contacted")
        create_lead(company_name="C", status="new")
        
        new_leads = list_leads(status="new")
        assert len(new_leads) == 2
        
        contacted = list_leads(status="contacted")
        assert len(contacted) == 1
        assert contacted[0]["company_name"] == "B"


class TestInteractions:
    """Test interaction logging."""

    def test_log_interaction(self, mock_db):
        """Should log an interaction."""
        lead = create_lead(email="test@example.com")
        
        interaction = log_interaction(
            lead_id=lead["id"],
            channel="email",
            direction="outbound",
            message_type="cold_outreach",
            content_preview="Hello...",
        )
        
        assert interaction["lead_id"] == lead["id"]
        assert interaction["status"] == "logged"


class TestPendingActions:
    """Test approval queue."""

    def test_queue_and_approve_action(self, mock_db):
        """Should queue and approve an action."""
        action = queue_action(
            action_type="send_message",
            description="Test message",
            payload={"to": "test@example.com"},
            urgency=1,
        )
        
        assert action["status"] == "pending"
        
        # Approve
        result = approve_action(action["id"], "samkit")
        assert result["status"] == "approved"
        
        # Verify not in pending list
        pending = list_pending_actions()
        assert len(pending) == 0


class TestFollowUps:
    """Test follow-up scheduling."""

    def test_get_stale_leads(self, mock_db):
        """Should find leads with no recent contact."""
        # Create a lead with old last_contact
        lead = create_lead(company_name="Stale Corp")
        
        # Manually set last_contact to old date
        from crm_toolkit import _get_db
        with _get_db() as conn:
            conn.execute(
                "UPDATE leads SET last_contact = '2020-01-01' WHERE id = ?",
                (lead["id"],),
            )
            conn.commit()
        
        stale = get_stale_leads(days=1)
        assert len(stale) >= 1
        assert any(s["company_name"] == "Stale Corp" for s in stale)
