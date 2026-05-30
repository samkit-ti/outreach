"""Tests for the outreach drafter."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills"))

from outreach_drafter import draft_email, draft_whatsapp


class TestDraftEmail:
    """Test email draft generation."""

    def test_draft_healthcare_cold_outreach(self):
        """Should generate healthcare-specific cold outreach prompt."""
        lead = {
            "id": "ld-test-001",
            "company_name": "Apollo Hospitals",
            "contact_name": "Dr. Patel",
            "industry": "healthcare",
            "notes": "Looking for patient intake automation",
        }
        
        draft = draft_email(lead, message_type="cold_outreach")
        
        assert draft["lead_id"] == "ld-test-001"
        assert draft["message_type"] == "cold_outreach"
        assert "prompt" in draft
        # Verify healthcare context is in the prompt
        assert "healthcare" in draft["prompt"].lower()
        assert "Apollo Hospitals" in draft["prompt"]

    def test_draft_education_follow_up(self):
        """Should generate education-specific follow-up."""
        lead = {
            "id": "ld-test-002",
            "company_name": "DAV School",
            "contact_name": "Principal Sharma",
            "industry": "education",
            "notes": "Interested in tutoring agents",
        }
        
        draft = draft_email(lead, message_type="follow_up")
        
        assert draft["message_type"] == "follow_up"
        assert "education" in draft["prompt"].lower()

    def test_draft_whatsapp(self):
        """WhatsApp drafts should be shorter."""
        lead = {
            "id": "ld-test-003",
            "company_name": "Test Co",
            "contact_name": "Test",
            "industry": "general",
        }
        
        draft = draft_whatsapp(lead, message_type="follow_up")
        
        assert draft["template_id"].startswith("whatsapp_")
        assert "whatsapp" in draft["prompt"].lower()
        assert "80 words" in draft["prompt"].lower()
