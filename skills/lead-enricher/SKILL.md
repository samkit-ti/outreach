---
name: lead-enricher
description: "Research and enrich lead data using web search and LLM synthesis"
version: 1.0.0
author: PS3Labs
license: MIT
metadata:
  hermes:
    tags: [sales, leads, enrichment, research]
    related_skills: [outreach-drafter, crm-toolkit, sherlock-research]
    requires_env:
      - AZURE_FOUNDRY_API_KEY
      - AZURE_FOUNDRY_BASE_URL
    optional_env:
      - CLEARBIT_API_KEY
      - APOLLO_API_KEY
      - HUNTER_API_KEY
---

# Lead Enricher

Enrich lead records with company intelligence, decision makers, tech stack, and pain points using web search + LLM synthesis.

## When to Use

- A new lead has minimal information (just email/company name)
- You need to personalize outreach but lack context
- Preparing for a sales call or demo

## Commands

- `/enrich-lead <lead-id>` — Research and update a single lead
- `/enrich-batch <lead-id-1> <lead-id-2> ...` — Batch enrichment (max 10)

## How It Works

1. Extract domain from lead email
2. Run web searches for:
   - Company profile (size, industry, funding)
   - Key decision makers (LinkedIn, about page)
   - Technology stack (BuiltWith, job postings)
   - Recent news (funding, expansions)
3. Synthesize findings via LLM into structured JSON
4. Update CRM record with enrichment data

## Output Format

```json
{
  "company_size": "50-200 employees",
  "industry_sub": "private hospital chain",
  "decision_makers": [
    {"name": "Dr. Patel", "title": "Head of Operations", "source": "LinkedIn"}
  ],
  "tech_stack": ["Salesforce", "Epic EMR"],
  "recent_news": ["Raised $5M Series A (Jan 2026)"],
  "inferred_pain_points": ["patient wait times", "staff scheduling"],
  "fit_score": 78,
  "fit_reasoning": "Strong match: healthcare, growing, no AI automation visible",
  "sources": ["url1", "url2"]
}
```

## Guardrails

- Never scrape behind paywalls
- Respect robots.txt
- Only use publicly available information
- Mark missing data as "Not found" rather than hallucinating
