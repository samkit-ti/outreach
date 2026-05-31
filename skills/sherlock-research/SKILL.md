---
name: sherlock-research
description: "Deep research skill using web search, Exa, and LLM synthesis to gather intelligence on companies, markets, and trends"
version: 1.0.0
author: PS3Labs
license: MIT
metadata:
  hermes:
    tags: [research, intelligence, web-search, market-research]
    related_skills: [lead-enricher, outreach-drafter]
    requires_env:
      - AZURE_FOUNDRY_API_KEY
      - AZURE_FOUNDRY_BASE_URL
    optional_env:
      - EXA_API_KEY
      - FIRECRAWL_API_KEY
      - TAVILY_API_KEY
---

# Sherlock Research

Deep research capability for sales intelligence. Uses web search + LLM synthesis to gather comprehensive information about companies, markets, competitors, and industry trends.

## When to Use

- Preparing for a sales call (deep-dive on prospect)
- Market research for new verticals
- Competitive intelligence
- Trend analysis for outreach angles
- Validating a lead's fit score

## Commands

- `/research-company <company-name> [domain]` — Full company intelligence report
- `/research-market <industry> [location]` — Market landscape report
- `/research-competitor <company-name>` — Competitive positioning analysis
- `/research-trend <topic>` — Emerging trend analysis

## Sources

Priority order:
1. **Exa** (if `EXA_API_KEY` set) — Neural web search, best for semantic research
2. **Firecrawl** (if `FIRECRAWL_API_KEY` set) — Web scraping + Markdown extraction
3. **Tavily** (if `TAVILY_API_KEY` set) — AI search engine with sources
4. **DuckDuckGo** (fallback) — Free, no API key required

## Output Format

### Company Research
```
# [Company Name] — Intelligence Report

## Overview
- Founded: YYYY
- Employees: XXX
- HQ: Location
- Industry: Vertical

## Leadership
- CEO: Name
- CTO: Name
- Key decision makers for AI/automation

## Technology Stack
- Current tools and platforms
- Integration opportunities

## Recent Developments
- Funding rounds
- Product launches
- Partnerships

## Pain Points (Inferred)
1. ...
2. ...

## PS3Labs Fit
- Score: X/100
- Recommended approach: ...
```

## Guardrails

- Only use publicly available information
- Cite sources for all claims
- Distinguish between fact and inference
- Respect data privacy (no scraping personal info)
