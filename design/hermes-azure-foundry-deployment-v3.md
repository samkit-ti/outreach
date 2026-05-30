# Design v3 Extension: Academic Outreach + Career Applications

**Parent Design:** `hermes-azure-foundry-deployment-v2.md`  
**Reference Architecture:** `AUTONOMOUS_DEV_TEAM.md`  
**Extension Scope:** Personal career advancement — research, jobs, accelerators  
**Date:** 2026-05-30  

---

## 1. What Changed

The agent is no longer just a **sales/marketing team** for PS3Labs. It is now also your **personal career advancement assistant**. Three new high-stakes capabilities:

| Capability | Persona | Risk Level | Human Approval |
|---|---|---|---|
| **Research outreach** | Academic | Medium | Required for sending |
| **Job applications** | Career | **Critical** | Required for every application |
| **Accelerator applications** | Founder | **Critical** | Required for every application |

These personas share the same VM, same Kimi K2.6 backend, same beads workflow engine — but with **much stricter guardrails** because the stakes involve your personal reputation, legal commitments, and career trajectory.

---

## 2. New Personas

### Persona: Academic

```
You are an academic research assistant working on behalf of [Founder Name].
Your job is to identify professors and research labs aligned with [Founder]'s interests,
and draft personalized outreach emails expressing genuine interest in collaboration.

FOUNDER PROFILE:
- Background: [to be filled from resume]
- Research interests: [to be configured]
- Goal: Secure research collaborations, co-authored papers, or research assistant positions
- Geographic preference: [to be configured]

YOUR CAPABILITIES:
- Search for professors by research area, university, recent publications
- Read and summarize professor's recent work (last 2-3 papers)
- Draft personalized emails that demonstrate genuine alignment
- Track outreach status (sent → no reply → follow-up → meeting)
- Prepare research proposals or project summaries if requested

TONE:
- Humble, intellectually curious, professionally ambitious
- Show you've actually read their work (cite specific papers/concepts)
- No generic "I'm a big fan of your research" — be specific
- Respectful of professor's time; concise but substantive

GUARDRAILS:
- NEVER send an email without human approval. Draft only.
- Never claim expertise you don't have.
- Never spam multiple professors at the same university simultaneously.
- Wait at least 7 days before follow-up.
- If a professor declines, log it and never contact again unless instructed.
- All emails must include the founder's real name and actual credentials.
```

### Persona: Career

```
You are a career strategist and job application assistant for [Founder Name].
Your job is to find relevant job opportunities, prepare materials, and manage applications.

FOUNDER PROFILE:
- Skills: [extracted from resume]
- Experience: [extracted from resume]
- Target roles: [to be configured — e.g., "AI Engineer", "Founding Engineer", "ML Researcher"]
- Target companies: [to be configured — startups, big tech, research labs]
- Geographic preference: [to be configured]
- Salary expectations: [optional, confidential]

YOUR CAPABILITIES:
- Monitor job boards for relevant postings (LinkedIn, Indeed, Naukri, AngelList, etc.)
- Score job fit based on skills alignment, company stage, location
- Draft tailored cover letters and application emails
- Fill out application forms (where API/structured data is available)
- Track application status and follow-up timing
- Prepare for interviews (company research, likely questions)

TONE:
- Professional, confident but not arrogant
- Cover letters should tell a compelling story, not just repeat the resume
- Match the company's voice (startup = direct; big tech = structured)

GUARDRAILS:
- **NEVER submit an application without explicit human approval.** This is non-negotiable.
- Never apply to the same position twice.
- Never inflate credentials or experience.
- Never ghost a recruiter — if you start a conversation, log it and track it.
- Keep all application materials truthful and accurate.
- Founder must review every cover letter before sending.
- Do not share resume with third-party recruiters without permission.
```

### Persona: Founder (Accelerator Mode)

```
You are a founder applying to startup accelerator programs on behalf of PS3 Labs AI.
Your job is to identify relevant accelerators, track deadlines, and draft applications.

COMPANY PROFILE:
- Name: PS3 Labs AI
- Tagline: "AI Agents That Work While You Sleep"
- Focus: AI agents for healthcare and education in India
- Stage: [pre-seed / seed / etc.]
- Traction: [to be filled — pilots, revenue, users, etc.]
- Team: [founder background, any co-founders]
- Ask: [funding amount, mentoring needs, network access]

YOUR CAPABILITIES:
- Monitor accelerator programs (YC, Techstars, Sequoia Surge, Accel, Blume, etc.)
- Track application deadlines and requirements
- Draft application essays, video scripts, and pitch narratives
- Prepare one-pagers and executive summaries
- Research alumni companies and tailor applications

TONE:
- Visionary but grounded in data
- Show ambition, but back it with traction or strong validation
- Accelerator-specific: YC wants technical founders; Sequoia wants large markets

GUARDRAILS:
- **NEVER submit an application without human approval.**
- Never misrepresent traction, revenue, or team size.
- Never apply to the same accelerator batch twice.
- Respect NDAs and confidentiality terms of any current pilots/partners.
- All financial claims must be verifiable.
```

---

## 3. New Skills

### 3.1 `resume_parser`

**Purpose:** Extract structured data from your resume/CV.

**Input:** PDF/DOCX resume file  
**Output:** JSON with:
```json
{
  "name": "Samkit Shah",
  "email": "samkit@ps3labs.ai",
  "phone": "+91...",
  "location": "Ahmedabad, India",
  "summary": "...",
  "skills": ["Python", "Machine Learning", "AI Agents", "..."],
  "experience": [
    {
      "company": "PS3 Labs AI",
      "role": "Founder",
      "duration": "2025-Present",
      "highlights": ["Built AI agents for healthcare", "..."]
    }
  ],
  "education": [
    {
      "institution": "...",
      "degree": "B.Tech / M.Tech / PhD",
      "field": "Computer Science",
      "year": "20XX"
    }
  ],
  "publications": [...],
  "projects": [...],
  "links": {
    "linkedin": "...",
    "github": "...",
    "portfolio": "..."
  }
}
```

**Storage:** Parsed resume lives in `/opt/ps3labs/vault/resume.json` (encrypted at rest). The agent reads this to personalize outreach but never exposes raw PII in logs.

### 3.2 `professor_finder`

**Purpose:** Find professors whose research aligns with your interests.

**Input:** Research keywords, universities (optional), geographic filters  
**Output:** List of professors with:
- Name, title, university, department
- Recent publications (last 2-3 years)
- Research summary (auto-generated)
- Contact email (if public)
- Fit score (0-100)

**Sources:** Google Scholar, university websites, arXiv, ResearchGate, Semantic Scholar

### 3.3 `research_matcher`

**Purpose:** Match your background/interests to a professor's work and generate a "connection narrative."

**Input:** `resume_parser` output + `professor_finder` output  
**Output:** A 2-3 paragraph narrative explaining:
- Why this professor's work is relevant to you
- Specific papers/concepts that resonate
- What you can contribute (skills, perspective)
- Proposed collaboration angle

### 3.4 `job_scout`

**Purpose:** Find job postings matching your profile.

**Input:** Target roles, skills, location preferences, company stage preferences  
**Output:** Ranked list of jobs with:
- Title, company, location, salary (if listed)
- Fit score (skill overlap)
- Application link
- Deadline
- Company context (funding stage, size, recent news)

**Sources:** LinkedIn Jobs API, Indeed, Naukri, AngelList, Y Combinator Work at a Startup, company career pages

### 3.5 `application_drafter`

**Purpose:** Draft application materials.

**Modes:**
- **Cover letter:** Given job posting + your resume → tailored cover letter
- **Research email:** Given professor profile + your background → personalized outreach
- **Accelerator essay:** Given accelerator prompt + company profile → application essay
- **Cold email (networking):** Given target person + context → warm intro request

**Output:** Draft text + metadata (word count, key points covered, suggested improvements)

### 3.6 `accelerator_tracker`

**Purpose:** Monitor accelerator programs.

**Database:** `/opt/ps3labs/accelerators.json`
```json
[
  {
    "name": "Y Combinator",
    "batch": "W27",
    "application_opens": "2026-08-01",
    "application_deadline": "2026-09-15",
    "requirements": ["video", "essays", "demo"],
    "status": "tracking",
    "notes": "Strong alumni in Indian AI space"
  }
]
```

**Actions:**
- Weekly scan for new programs and deadline changes
- Alert founder 14 days and 3 days before deadline
- Auto-create beads task when deadline approaches

### 3.7 `form_filler` (Future / Optional)

**Purpose:** Auto-fill web application forms.

**Method:** Browser automation (Playwright) with structured resume data.
**Guardrail:** NEVER auto-submit. Fill only, pause for human review.
**Warning:** Complex multi-page forms with custom fields often fail. Use with caution.

---

## 4. Data Schema Extensions

### 4.1 `professors` Table

```sql
CREATE TABLE professors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    university TEXT NOT NULL,
    department TEXT,
    title TEXT,                    -- Professor, Associate Prof, etc.
    research_areas TEXT,           -- JSON array
    recent_papers TEXT,            -- JSON array: [{title, url, year, summary}]
    email TEXT,
    website TEXT,
    scholar_id TEXT,
    fit_score INTEGER,             -- 0-100
    outreach_status TEXT,          -- identified → drafted → approved → sent → replied → meeting → declined → collab
    last_contact TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.2 `applications` Table

```sql
CREATE TABLE applications (
    id TEXT PRIMARY KEY,
    application_type TEXT,         -- job | accelerator | research_position | fellowship
    target_name TEXT,              -- Company name, accelerator name, university
    target_role TEXT,              -- Job title, program name, research area
    source_url TEXT,               -- Link to posting
    status TEXT,                   -- discovered → drafted → pending_approval → submitted → phone_screen → interview → offer → accepted → rejected → withdrawn
    fit_score INTEGER,
    materials TEXT,                -- JSON: {cover_letter_path, resume_version, portfolio_link, etc.}
    deadline TIMESTAMP,
    submitted_at TIMESTAMP,
    followed_up_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.3 `accelerators` Table

```sql
CREATE TABLE accelerators (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    batch TEXT,
    location TEXT,
    focus_areas TEXT,              -- JSON array: ["AI", "Healthcare", "India"]
    investment_terms TEXT,         -- "$500K for 7%"
    application_opens TIMESTAMP,
    application_deadline TIMESTAMP,
    requirements TEXT,             -- JSON array
    status TEXT,                   -- tracking → preparing → pending_approval → submitted → interview → accepted → declined
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5. Workflow Formulas (Beads)

### Formula: `research-outreach`

```json
{
  "name": "research-outreach",
  "description": "End-to-end professor outreach for research collaboration",
  "steps": [
    { "step": 1, "title": "Find Professors", "skill": "professor_finder", "auto": true, "output": "professor_list" },
    { "step": 2, "title": "Score Fit", "skill": "research_matcher", "auto": true, "input": "professor_list", "output": "scored_professors" },
    { "step": 3, "title": "Draft Outreach", "skill": "application_drafter", "auto": true, "input": "scored_professors[0]", "output": "draft_email" },
    { "step": 4, "title": "Human Approval", "gate": "human_approve", "auto": false, "input": "draft_email" },
    { "step": 5, "title": "Send Email", "skill": "send_message", "auto": true, "input": "approved_email" },
    { "step": 6, "title": "Log to CRM", "skill": "crm_log", "auto": true },
    { "step": 7, "title": "Schedule Follow-up", "skill": "follow_up_scheduler", "auto": true, "delay": "7d" }
  ]
}
```

### Formula: `job-application`

```json
{
  "name": "job-application",
  "description": "Apply to a job posting with human approval at every step",
  "steps": [
    { "step": 1, "title": "Scout Jobs", "skill": "job_scout", "auto": true, "output": "job_listings" },
    { "step": 2, "title": "Score Fit", "skill": "fit_scorer", "auto": true, "input": "job_listings", "output": "ranked_jobs" },
    { "step": 3, "title": "Founder Selects", "gate": "human_select", "auto": false, "input": "ranked_jobs", "output": "selected_job" },
    { "step": 4, "title": "Draft Materials", "skill": "application_drafter", "auto": true, "input": "selected_job", "output": "application_package" },
    { "step": 5, "title": "Founder Reviews", "gate": "human_approve", "auto": false, "input": "application_package" },
    { "step": 6, "title": "Submit Application", "skill": "form_filler_or_email", "auto": false, "input": "approved_package", "note": "Human may choose to submit manually" },
    { "step": 7, "title": "Log Application", "skill": "crm_log", "auto": true }
  ]
}
```

### Formula: `accelerator-application`

```json
{
  "name": "accelerator-application",
  "description": "Prepare and submit accelerator application",
  "steps": [
    { "step": 1, "title": "Track Deadlines", "skill": "accelerator_tracker", "auto": true, "output": "upcoming_deadlines" },
    { "step": 2, "title": "Alert Founder", "skill": "discord_notify", "auto": true, "input": "upcoming_deadlines" },
    { "step": 3, "title": "Draft Application", "skill": "application_drafter", "auto": true, "input": "accelerator_requirements", "output": "draft_application" },
    { "step": 4, "title": "Multiple Review Rounds", "gate": "human_approve", "auto": false, "input": "draft_application" },
    { "step": 5, "title": "Final Approval", "gate": "human_approve_final", "auto": false, "input": "revised_application" },
    { "step": 6, "title": "Submit", "skill": "form_filler", "auto": false, "note": "Human submits or supervises" },
    { "step": 7, "title": "Log and Track", "skill": "crm_log", "auto": true }
  ]
}
```

---

## 6. Privacy & Security

### 6.1 Resume Vault

```
/opt/ps3labs/vault/
├── resume.json           # Structured resume data
├── resume_original.pdf   # Original file
├── transcript.pdf        # Academic transcript (if applicable)
├── portfolio/            # Project screenshots, demos
│   ├── ps3labs_website.png
│   └── demo_video.mp4
└── references/           # Reference letters, recommendations
```

- **Encryption at rest:** The entire `/opt/ps3labs/vault/` directory is encrypted using `gocryptfs` or `encfs`.
- **Access control:** Only the Hermes process and the founder (via SSH) can read it.
- **Logs:** The agent logs that it "read resume" but never logs the content of PII fields.
- **Exfiltration guard:** Resume data is never sent to external APIs except in the context of drafting an application (and even then, only the relevant parts).

### 6.2 Application History Privacy

- The `applications` table tracks what you applied to, but the `materials` column only stores **file paths**, not the full text of cover letters.
- Full cover letters live in the vault and are only read when needed.
- If the VM is compromised, an attacker sees "applied to YC W27" but not the essay content.

---

## 7. Guardrails (Elevation from v2)

| Action | v2 (Sales/Marketing) | v3 (Career/Academic) |
|---|---|---|
| Send cold email | Auto if <50/day, human if >50 | **ALWAYS human approve** |
| Send WhatsApp | Auto for warm leads | **ALWAYS human approve** |
| Public content | Human approve | Same |
| **Submit job application** | N/A | **Blocked without explicit human action** |
| **Send research email** | N/A | **Blocked without explicit human action** |
| **Submit accelerator app** | N/A | **Blocked without explicit human action** |
| Update resume | N/A | **Human only** (agent suggests, founder edits) |
| Share references | N/A | **Human only** |

### The Golden Rule for Career Mode:
> **The agent is a draft writer and research analyst, not an actor.** It finds opportunities, drafts materials, and queues them for your approval. It never clicks "submit" on your behalf.

---

## 8. Integration with Existing Architecture

```
                    ┌─────────────────────────┐
                    │   HERMES GATEWAY (VM)   │
                    │                         │
  ┌─────────────┐   │  ┌───────┐ ┌────────┐  │   ┌─────────────┐
  │   SALES     │◄──┤  │ Sales │ │Marketing│  ├──►│  DISCORD    │
  │  PERSONA    │   │  └───┬───┘ └────┬───┘  │   │  (Founder)  │
  └─────────────┘   │      │          │      │   └─────────────┘
  ┌─────────────┐   │  ┌───┴──────────┴───┐  │   ┌─────────────┐
  │   ACADEMIC  │◄──┤  │   SHARED MEMORY  │  ├──►│   EMAIL     │
  │  PERSONA    │   │  │  (CRM, beads,    │  │   │  (Gmail)    │
  └─────────────┘   │  │   evolution)     │  │   └─────────────┘
  ┌─────────────┐   │  └──────────────────┘  │   ┌─────────────┐
  │   CAREER    │◄──┤  ┌───────┐ ┌────────┐  ├──►│  WHATSAPP   │
  │  PERSONA    │   │  │Research│ │Founder │  │   │  (Baileys)  │
  └─────────────┘   │  │Persona │ │(Accel) │  │   └─────────────┘
                    │  └───────┘ └────────┘  │
                    └─────────────────────────┘
```

The new personas (Academic, Career, Founder/accelerator) sit alongside Sales and Marketing. They share:
- The same Kimi K2.6 backend
- The same CRM database (with new tables)
- The same beads workflow engine
- The same Discord/email/WhatsApp channels
- The same evolution engine (patterns extracted from academic/career interactions feed back into rules)

But they have **separate system prompts, separate guardrails, and separate formulas**.

---

## 9. Founder Command Interface

You interact with the new personas via Discord (or email) using natural language. Examples:

```
You: "Find professors in India working on AI for healthcare"
Agent: "Found 15 professors. Top 5: [list]. Shall I draft outreach for any?"

You: "Apply to this YC job posting: https://..."
Agent: "Scouted the role. Fit score: 87/100. Drafting cover letter... [draft attached]. /approve to send?"

You: "What accelerators are open right now?"
Agent: "3 programs with deadlines in next 30 days: [list]. YC W27 (due Sept 15) is strongest fit. Shall I start drafting?"

You: "That professor email was too formal. Make it more conversational."
Agent: "✅ Rule created: academic_outreach.tone = 'conversational'. Updated draft: [new draft]."
```

---

## 10. Implementation Additions to v2 Roadmap

### Phase 3b: Career & Academic Skills (Week 3–4)
- [ ] Implement `resume_parser` (PDF/DOCX → JSON)
- [ ] Implement `professor_finder` (Google Scholar + university search)
- [ ] Implement `research_matcher` (alignment narrative generator)
- [ ] Implement `job_scout` (LinkedIn + Indeed + AngelList scraping)
- [ ] Implement `application_drafter` (cover letter, research email, accelerator essay modes)
- [ ] Implement `accelerator_tracker` (deadline monitoring)
- [ ] Create vault directory + encryption setup
- [ ] Import founder resume into vault

### Phase 4b: Career & Academic Workflows (Week 4–5)
- [ ] Wire `research-outreach` formula to Hermes
- [ ] Wire `job-application` formula to Hermes
- [ ] Wire `accelerator-application` formula to Hermes
- [ ] Set up job board monitoring cron (daily)
- [ ] Set up accelerator deadline monitoring cron (weekly)
- [ ] Test end-to-end: job found → draft created → Discord approval → sent

---

## 11. Open Questions (Founder)

These answers will let me configure the personas precisely:

1. **Resume location/format:** Where is your current resume? PDF, Word, or online (LinkedIn)?
2. **Research interests:** What research areas excite you? (e.g., "AI agents for healthcare", "multimodal LLMs", "AI in education")
3. **Target professors:** Any specific universities or researchers you admire?
4. **Job targets:** What roles are you open to? (Founding engineer, AI researcher, PM, etc.)
5. **Geography:** Are you open to relocating? Remote-only? India-only?
6. **Accelerators:** Any specific programs you want to target? (YC, Techstars, Sequoia Surge, India-specific?)
7. **Approval preference:** Do you want to see drafts in Discord and approve there, or receive draft emails and reply to approve?

---

*Extension v3.0 | PS3Labs | 2026-05-30*
