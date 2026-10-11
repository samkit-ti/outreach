# Shared brief for job-search agents (today: 2026-10-11)

## Candidate
Samkit Shah. B.Tech CSE, IIT Jodhpur, 2020-2024. ~2.3 years experience:
- Trilogy Innovations (Aug 2025-present, remote): "Innovation Catalyst". Agentic LLM generators (99% pass on internal bench), converting agentic pipelines to SFT models (RAFT, DPO, GRPO on open models), automated video QC pipeline, led PoC->prod launch of a community platform (20+ campuses, $700k revenue, 1.5k DAU), cut geo-calculation API cost $50k->$3k. Stack: FastAPI, React, Angular, Supabase, PostgreSQL.
- Warner Bros. Discovery (Jul 2024-Aug 2025, Bangalore): Software/ML Engineer I. Project lead for ML service (work-order ETC, vendor recommendation), transcript/caption AI (-50% cost), Cadence->Temporal migration PoC. Stack: Java, Spring Boot, Hibernate, PostgreSQL, Cadence, RabbitMQ, Kafka, SNS/SQS.
- Latentforce AI (summer 2024, remote): AI Engineer. Open VLMs (CogVLM, Phi3, Gemma) for ID-document KIE, GPT knowledge graphs + contextual chunking for RAG. 95.6% acc, F1 0.83.
- OSS: Uber Cadence contributor (ongoing), PyNeuroML, The Virtual Brain.
- Research: VL2G lab IIT Jodhpur (DocAI, YOLO/DETR fine-tuning), bachelor thesis on Bayesian network structure learning.
- WorldQuant consultant (30+ alphas, avg Sharpe 2.1). ICPC'23 prelims AIR 223. JEE Advanced AIR 2005. National-level chess, internationally rated.

## Hard constraints
- India roles: FIXED CASH >= INR 50 lakh/yr for someone with 2-3 YOE (ESOPs/bonus do NOT count toward the floor). Include a role if the company's known band for that level clears 50L fixed even if the posting has no salary.
- International roles: >= USD 150k BASE or local equivalent (approx GBP 100k, EUR 110k, CHF 130k, SGD 180k, AED 500k, AUD 200k, CAD 180k). Must be either (a) remote-from-India / global remote, or (b) a company with a realistic sponsorship path for an Indian-passport holder (name the visa: UK Skilled Worker / HPI / Global Talent; Netherlands HSM; Germany Blue Card; Ireland CSEP; Singapore EP; UAE employment visa/Golden Visa; Australia 482/186; US O-1 or H-1B lottery, Canada GTS). Be honest about realism.
- Experience bar: role must accept 2-3 YOE (SDE2 / "Software Engineer II" / "Engineer" / mid-level). Skip Senior/Staff roles that demand 5+ years. Skip roles requiring a PhD unless they say "or equivalent experience".
- Work mode: remote preferred, hybrid/onsite fine. India onsite: any metro (Bangalore, Hyderabad, Pune, Mumbai, Delhi NCR, Chennai, Ahmedabad).
- Timeline: can start in 2-3 months (60-day notice). Roles must be currently open or company must be actively hiring this profile.
- EXCLUDE: Warner Bros. Discovery; IT services/consulting (TCS, Infosys, Wipro, HCL, Accenture, Cognizant, Capgemini, Deloitte, EY, LTIMindtree, Tech Mahindra, Persistent, Mphasis, EPAM, Globant, Thoughtworks-style bodyshops); pre-seed or unfunded startups (a startup qualifies only with a disclosed raise, a YC/notable accelerator batch, or clearly > ~20 employees).

## Research rules (strict)
- NEVER invent a posting. Every row must come from a WebSearch result or a page you fetched with WebFetch.
- Prefer the company's own careers page or ATS (Greenhouse, Lever, Ashby, Workday, SmartRecruiters) URL over LinkedIn/Naukri/Indeed aggregator links. If only an aggregator link exists, use it but say so.
- Try to WebFetch each posting URL. If it loads and matches, status = "verified_open_2026-10-11". If you could not fetch it, status = "search_result_unverified".
- Comp: use posted bands first; else levels.fyi, Glassdoor, AmbitionBox, Blind, or recent news. Give a number or range and name the source. If unknown say "unknown" and set comp_confidence "low".
- Aim for 15-25 rows per agent. Quality over quantity; 12 solid verified rows beat 30 guesses.
- Also include up to 5 "companies to watch" rows (company actively hiring this profile, careers page URL, but no single matching req you could verify) with status "company_hiring_no_specific_req".

## Output format
Write a single JSON array to the file path given in your task. Each element:
{
  "bucket": "<india_ai | fde_startup | india_sde | quant | intl_uk_eu_us | intl_apac_me>",
  "company": "",
  "role": "",
  "url": "",
  "location": "",
  "work_mode": "remote | hybrid | onsite | remote-from-India | relocation",
  "yoe_required": "",
  "comp_estimate": "",
  "comp_source": "",
  "comp_confidence": "high | med | low",
  "visa_path": "",            // "" for India roles
  "fit_score": 1-5,           // 5 = near-perfect match to resume
  "fit_notes": "",            // 1-2 sentences tying to specific resume items
  "status": "verified_open_2026-10-11 | search_result_unverified | company_hiring_no_specific_req",
  "notes": ""                 // deadlines, cons, interview process, anything useful
}
Then reply with a 10-line summary: how many rows, top 5 picks, anything you could not verify.
