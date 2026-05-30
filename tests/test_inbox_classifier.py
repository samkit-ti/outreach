"""Tests for the inbox classifier."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills"))

from inbox_classifier import classify_message, get_auto_reply_decision, InboxCategory


class TestClassifyMessage:
    """Test message classification."""

    def test_classify_hot_lead(self):
        """Should classify high-intent message as hot_lead."""
        result = classify_message(
            subject="Interested in your AI agents",
            body="We are a hospital chain looking to automate patient intake. Can we schedule a demo this week?",
            from_email="cto@hospital.com",
        )
        
        assert "prompt" in result
        assert result["from_email"] == "cto@hospital.com"

    def test_auto_reply_decision_hot_lead(self):
        """Hot leads with high confidence should auto-reply."""
        classification = {
            "category": "hot_lead",
            "confidence": 0.85,
            "urgency": "high",
        }
        
        decision = get_auto_reply_decision(classification)
        assert decision["action"] == "auto_reply"

    def test_auto_reply_decision_objection(self):
        """Objections should go to human review."""
        classification = {
            "category": "objection",
            "confidence": 0.9,
        }
        
        decision = get_auto_reply_decision(classification)
        assert decision["action"] == "human_review"

    def test_auto_reply_decision_low_confidence(self):
        """Low confidence should go to human review."""
        classification = {
            "category": "general",
            "confidence": 0.4,
        }
        
        decision = get_auto_reply_decision(classification)
        assert decision["action"] == "human_review"

    def test_spam_ignored(self):
        """Spam should be ignored."""
        classification = {
            "category": "spam",
            "confidence": 0.95,
        }
        
        decision = get_auto_reply_decision(classification)
        assert decision["action"] == "ignore"
