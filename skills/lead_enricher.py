"""PS3Labs Lead Enricher — Web research to fill missing lead data."""

import json
import re
import time
from urllib.parse import urljoin, urlparse


def _safe_get_domain(email: str) -> str | None:
    """Extract domain from email."""
    if "@" in email:
        return email.split("@")[-1].strip().lower()
    return None


def build_research_prompt(lead: dict) -> dict:
    """Build a web research prompt for enriching a lead.

    Returns dict with search queries and prompt for the LLM to synthesize.
    """
    company = lead.get("company_name", "")
    email = lead.get("email", "")
    domain = _safe_get_domain(email)

    queries = []
    if company:
        queries.append(f'"{company}" AI automation OR chatbot OR digital transformation')
        queries.append(f'"{company}" Ahmedabad OR Gujarat site:linkedin.com')
    if domain:
        queries.append(f'site:{domain} about OR team OR technology')

    # Prompt for the LLM to do structured research
    prompt = f"""You are a market intelligence researcher. Find information about this company.

COMPANY: {company}
DOMAIN: {domain}
EMAIL: {email}

SEARCH QUERIES (run these via web_search tool):
{json.dumps(queries, indent=2)}

ENRICHMENT GOALS:
1. Company size (employees, revenue if public)
2. Industry sub-vertical (e.g., "private hospital chain", "K-12 school group")
3. Key decision makers (CTO, Director of Operations, Principal, etc.)
4. Technology stack (do they already use any AI/automation tools?)
5. Recent news (funding, expansions, partnerships — anything that creates urgency)
6. Pain points you can infer from their public info
7. Fit score for PS3 Labs AI (0-100) with reasoning

For each search result, extract 1-2 key facts. Be concise.

OUTPUT JSON:
{{
  "company_size": "...",
  "industry_sub": "...",
  "decision_makers": [{{"name": "...", "title": "...", "source": "..."}}],
  "tech_stack": ["..."],
  "recent_news": ["..."],
  "inferred_pain_points": ["..."],
  "fit_score": 75,
  "fit_reasoning": "...",
  "sources": ["url1", "url2"]
}}

IMPORTANT:
- Only use information from the search results.
- If info is not found, say "Not found" rather than guessing.
- Respect robots.txt. Do not scrape behind paywalls.
"""

    return {
        "lead_id": lead.get("id"),
        "company": company,
        "search_queries": queries,
        "prompt": prompt,
    }


def merge_enrichment(lead: dict, enrichment: dict) -> dict:
    """Merge enrichment data back into a lead record.

    Returns updated lead fields (not saved — caller calls crm_toolkit.update_lead).
    """
    updates = {}

    # Update industry if we found a better sub-vertical
    if enrichment.get("industry_sub"):
        updates["industry"] = enrichment["industry_sub"]

    # Add pain points to notes
    pain_points = enrichment.get("inferred_pain_points", [])
    if pain_points:
        notes = lead.get("notes", "")
        pain_text = " | Pain points: " + "; ".join(pain_points)
        updates["notes"] = (notes + pain_text)[:2000]  # Cap length

    return updates


# ---------------------------------------------------------------------------
# Batch enrichment
# ---------------------------------------------------------------------------

def enrich_leads_batch(lead_ids: list[str]) -> list[dict]:
    """Enrich multiple leads. Returns list of enrichment results.

    In production, this is called by a cron job or background task.
    """
    try:
        from .crm_toolkit import get_lead
    except ImportError:
        get_lead = lambda x: None

    results = []
    for lid in lead_ids[:10]:  # Rate limit: max 10 per batch
        lead = get_lead(lid)
        if not lead:
            continue
        research = build_research_prompt(lead)
        results.append(research)
        time.sleep(2)  # Be polite to search APIs
    return results


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_lead = {
        "id": "ld-enrich-test",
        "company_name": "Zydus Hospital Ahmedabad",
        "email": "info@zydushospitals.com",
        "industry": "healthcare",
        "notes": "",
    }
    result = build_research_prompt(test_lead)
    print(json.dumps(result, indent=2, default=str))
