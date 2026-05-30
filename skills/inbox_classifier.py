"""PS3Labs Inbox Classifier — Classifies inbound messages by intent."""

import json
from typing import Literal

InboxCategory = Literal[
    "hot_lead",           # High intent, ready to buy
    "pricing_inquiry",    # Asking about pricing
    "product_question",   # Feature/technical question
    "meeting_request",    # Wants a call/demo
    "objection",          # Concern or complaint
    "partner_inquiry",    # Potential partnership
    "press_inquiry",      # Media/journalist
    "job_inquiry",        # Asking about careers
    "spam",               # Unsolicited sales/promo
    "unsubscribe",        # Wants to opt out
    "general",            # Catch-all
]

INTENT_PROMPT = """
You are an inbox classifier for PS3 Labs AI.
Classify the incoming message into exactly one category.

CATEGORIES:
- hot_lead: Expresses strong interest, mentions budget/timeline, asks for next steps
- pricing_inquiry: Explicitly asks about cost, pricing, packages
- product_question: Asks how something works, features, technical details
- meeting_request: Asks for a call, demo, meeting, site visit
- objection: Expresses concern, doubt, or complaint (price too high, not ready, etc.)
- partner_inquiry: Wants to partner, resell, integrate, or collaborate
- press_inquiry: Journalist, blogger, or media request
- job_inquiry: Wants to work for PS3 Labs AI
- spam: Unsolicited sales, generic pitch, irrelevant
- unsubscribe: Wants to stop receiving messages
- general: None of the above, casual inquiry

OUTPUT JSON:
{
  "category": "one of the above",
  "confidence": 0.0-1.0,
  "sentiment": "positive|neutral|negative",
  "urgency": "low|medium|high|critical",
  "key_entities": ["company names", "people", "products mentioned"],
  "suggested_response_type": "auto_reply|human_review|queue_for_sales",
  "reasoning": "one sentence explanation"
}
"""


def classify_message(
    subject: str = "",
    body: str = "",
    from_email: str = "",
    channel: str = "email",
) -> dict:
    """Classify an inbound message.

    Returns dict with category, confidence, sentiment, urgency, suggested action.
    """
    prompt = f"""{INTENT_PROMPT}

INCOMING MESSAGE:
Channel: {channel}
From: {from_email}
Subject: {subject}
Body:
{body}

Classify now."""

    # In production, this calls the LLM. Here we return the prompt structure.
    return {
        "prompt": prompt,
        "channel": channel,
        "from_email": from_email,
        "subject_preview": subject[:100] if subject else "",
    }


def get_auto_reply_decision(classification: dict) -> dict:
    """Based on classification, decide whether to auto-reply or queue for human."""
    category = classification.get("category", "general")
    confidence = classification.get("confidence", 0.5)
    urgency = classification.get("urgency", "medium")

    # Decision tree
    if category in ("spam", "unsubscribe"):
        return {"action": "ignore", "reason": "Low-value inbound"}

    if category == "hot_lead" and confidence > 0.8:
        return {"action": "auto_reply", "reason": "High-intent lead, immediate response"}

    if category in ("pricing_inquiry", "product_question") and confidence > 0.75:
        return {"action": "auto_reply", "reason": "Standard inquiry, template response"}

    if category in ("objection", "partner_inquiry", "press_inquiry"):
        return {"action": "human_review", "reason": f"High-stakes category: {category}"}

    if urgency == "critical":
        return {"action": "human_review", "reason": "Critical urgency flagged"}

    if category == "meeting_request" and confidence > 0.7:
        return {"action": "auto_reply", "reason": "Meeting request, suggest times"}

    return {"action": "human_review", "reason": "Low confidence or unclear intent"}


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test = classify_message(
        subject="Interested in AI agents for our hospital",
        body="Hi, I'm Dr. Sharma from Sterling Hospital Ahmedabad. We are looking to automate patient intake and appointment scheduling. Can you share pricing and do a demo?",
        from_email="dr.sharma@sterlinghospital.in",
    )
    print(json.dumps(test, indent=2, default=str))

    decision = get_auto_reply_decision({"category": "hot_lead", "confidence": 0.92, "urgency": "high"})
    print(json.dumps(decision, indent=2))
