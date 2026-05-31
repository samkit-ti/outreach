---
name: outreach-drafter
description: "Draft personalized outreach emails and WhatsApp messages using lead context"
version: 1.0.0
author: PS3Labs
license: MIT
metadata:
  hermes:
    tags: [sales, outreach, drafting, email, whatsapp]
    related_skills: [lead-enricher, follow-up-scheduler, crm-toolkit]
    requires_env:
      - AZURE_FOUNDRY_API_KEY
      - AZURE_FOUNDRY_BASE_URL
---

# Outreach Drafter

Draft highly personalized outreach messages (email or WhatsApp) based on lead profile, industry, and enrichment data.

## When to Use

- Starting a new conversation with a cold lead
- Following up on a previous interaction
- Responding to pricing inquiries
- Requesting a meeting

## Commands

- `/draft-email <lead-id> [type]` — Draft email (types: cold_outreach, follow_up, pricing_response, meeting_request)
- `/draft-whatsapp <lead-id> [type]` — Draft WhatsApp message

## Message Types

| Type | Length | Framework | Use Case |
|------|--------|-----------|----------|
| cold_outreach | 150-200 words | PAS (Problem-Agitate-Solution) | First contact |
| follow_up | 80-120 words | Gentle reminder + new value | Re-engagement |
| pricing_response | 120-180 words | Value-first, then pricing | Price inquiry |
| meeting_request | 80-120 words | Direct + value proposition | Booking a call |

## Personalization Sources

1. **Lead profile** (company, contact, industry)
2. **Enrichment data** (pain points, tech stack, recent news)
3. **Evolution rules** (tested patterns from past outreach)
4. **Industry-specific hints**:
   - Healthcare: ROI, compliance, patient outcomes
   - Education: personalization, scale, student outcomes
   - General: automation, cost savings, 24/7 ops

## Example

```
/draft-email ld-abc123 cold_outreach
```

Produces:
- Subject line
- Personalized body
- Recommended CTA
- Tone notes

## Guardrails

- Never promise features we don't have
- Pricing is "subject to discussion"
- If you don't know something, say "I'll get back to you"
- No hallucination allowed
