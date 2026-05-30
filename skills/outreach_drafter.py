"""PS3Labs Outreach Drafter — Personalizes outreach messages using lead context."""

import json
import os
from pathlib import Path

# Sales persona context (injected into prompt)
SALES_CONTEXT = """
You are the Sales Lead at PS3 Labs AI. Your job is to move prospects through the pipeline.

COMPANY:
- PS3 Labs AI builds AI agents for healthcare and education in India.
- Pricing: Starter ₹15K/mo, Professional ₹45K/mo, Enterprise ₹1.5L+/mo.
- Based in Ahmedabad, Gujarat. Serves pan-India.
- Differentiators: vertical expertise, DPDP compliance, Gujarati support, affordable pricing.

TONE:
- Professional but warm. Not robotic, not overly salesy.
- Use Indian business English naturally.
- Healthcare leads: emphasize ROI, compliance, patient outcomes.
- Education leads: emphasize personalization, scale, student outcomes.

RULES:
- Never promise features we don't have.
- Pricing quotes are suggestions; note "final pricing subject to discussion."
- If you don't know something, say you'll get back — don't hallucinate.
"""


def load_evolution_rules() -> list[dict]:
    """Load active evolution rules to personalize drafts."""
    try:
        from .crm_toolkit import get_active_rules
        return get_active_rules()
    except ImportError:
        return []


def draft_email(
    lead: dict,
    message_type: str = "cold_outreach",
    template_version: str = "v3",
    extra_context: str = "",
) -> dict:
    """Draft a personalized email for a lead.

    Args:
        lead: Lead dict from crm_toolkit (company_name, contact_name, industry, etc.)
        message_type: cold_outreach | follow_up | pricing_response | meeting_request
        template_version: Which template version to use
        extra_context: Any additional context (e.g., recent news, previous interaction)

    Returns:
        Dict with subject, body, template_id, and suggested_call_to_action
    """
    rules = load_evolution_rules()
    rules_text = "\n".join(
        f"- Rule: {r['condition']} → {r['action']} (priority: {r['priority']})"
        for r in rules[:5]
    )

    industry = lead.get("industry", "general")
    company = lead.get("company_name", "your company")
    contact = lead.get("contact_name", "there")

    # Build persona-specific context
    if industry == "healthcare":
        industry_hints = (
            "Focus on reducing admin burden, 24/7 patient support, "
            "DPDP compliance, and ROI in rupees. Mention specific agent types: "
            "Patient Intake, Diagnostic Support, Lab Report Interpreter."
        )
    elif industry == "education":
        industry_hints = (
            "Focus on personalized learning at scale, reducing teacher workload, "
            "student outcomes, and affordable pricing for Indian schools. "
            "Mention: Personalized Tutor, Exam Prep, Career Guidance agents."
        )
    else:
        industry_hints = (
            "Focus on automation, cost savings, and 24/7 operations. "
            "Highlight our Ahmedabad-based team with pan-India support."
        )

    # Template selection based on message_type
    templates = {
        "cold_outreach": {
            "framework": "PAS (Problem-Agitate-Solution)",
            "length": "150-200 words",
            "cta": "Request a 15-min call to explore",
        },
        "follow_up": {
            "framework": "Gentle reminder + new value",
            "length": "80-120 words",
            "cta": "Let me know if you have 10 minutes this week",
        },
        "pricing_response": {
            "framework": "Value-first, then pricing",
            "length": "120-180 words",
            "cta": "Schedule a demo to see the ROI calculator",
        },
        "meeting_request": {
            "framework": "Direct + value proposition",
            "length": "80-120 words",
            "cta": "Suggest 2-3 time slots",
        },
    }

    tmpl = templates.get(message_type, templates["cold_outreach"])

    # Assemble the draft using simple templating (Hermes/Kimi will refine this)
    # In production, this calls the LLM. Here we provide the prompt structure.
    prompt = f"""{SALES_CONTEXT}

EVOLUTION RULES (personalization guidelines):
{rules_text}

LEAD PROFILE:
- Company: {company}
- Contact: {contact}
- Industry: {industry}
- Notes: {lead.get('notes', 'N/A')}

INDUSTRY-SPECIFIC GUIDANCE:
{industry_hints}

MESSAGE TYPE: {message_type}
TEMPLATE VERSION: {template_version}
FRAMEWORK: {tmpl['framework']}
TARGET LENGTH: {tmpl['length']}

EXTRA CONTEXT:
{extra_context}

---

DRAFT a personalized email in the framework above. Output JSON:
{{
  "subject": " compelling subject line",
  "body": "email body text",
  "call_to_action": "{tmpl['cta']}",
  "tone_notes": "why this tone was chosen",
  "template_id": "{message_type}_{template_version}"
}}
"""

    # Return the prompt structure — the actual LLM call happens in the Hermes gateway
    return {
        "prompt": prompt,
        "lead_id": lead.get("id"),
        "message_type": message_type,
        "template_id": f"{message_type}_{template_version}",
        "target_length": tmpl["length"],
        "suggested_cta": tmpl["cta"],
    }


def draft_whatsapp(
    lead: dict,
    message_type: str = "follow_up",
    template_version: str = "v1",
) -> dict:
    """Draft a WhatsApp message (shorter, more casual)."""
    email_draft = draft_email(lead, message_type, template_version)

    prompt = f"""{email_draft['prompt']}

WHATSAPP-SPECIFIC INSTRUCTIONS:
- Keep it under 80 words.
- Use line breaks for readability.
- More casual than email but still professional.
- No formal sign-off needed.
- One clear ask.

Output JSON:
{{
  "body": "WhatsApp message text",
  "template_id": "whatsapp_{message_type}_{template_version}"
}}
"""

    return {
        "prompt": prompt,
        "lead_id": lead.get("id"),
        "message_type": message_type,
        "template_id": f"whatsapp_{message_type}_{template_version}",
    }


# ---------------------------------------------------------------------------
# CLI / Standalone usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/opt/hermes-agent/skills")
    from crm_toolkit import get_lead

    # Quick test
    test_lead = {
        "id": "ld-test-001",
        "company_name": "Apollo Hospitals Ahmedabad",
        "contact_name": "Dr. Patel",
        "industry": "healthcare",
        "notes": "Looking for patient intake automation",
    }
    draft = draft_email(test_lead, message_type="cold_outreach")
    print(json.dumps(draft, indent=2, default=str))
