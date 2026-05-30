-- PS3Labs Hermes Agent — CRM Schema
-- Run: sqlite3 /opt/hermes-agent/crm.db < init_schema.sql

-- ============================================
-- LEADS
-- ============================================
CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    company_name TEXT,
    contact_name TEXT,
    email TEXT,
    phone TEXT,
    industry TEXT,                 -- healthcare | education | general
    source TEXT,                   -- inbound | outbound | referral | event
    status TEXT DEFAULT 'new',     -- new | contacted | engaged | meeting | proposal | closed_won | closed_lost | nurture
    priority INTEGER DEFAULT 2,    -- 0-4 (P0-P4)
    assigned_persona TEXT DEFAULT 'sales',
    last_contact TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_industry ON leads(industry);
CREATE INDEX IF NOT EXISTS idx_leads_priority ON leads(priority);
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);

-- ============================================
-- INTERACTIONS
-- ============================================
CREATE TABLE IF NOT EXISTS interactions (
    id TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES leads(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    channel TEXT,                  -- email | whatsapp | discord | manual
    direction TEXT,                -- inbound | outbound
    message_type TEXT,             -- cold_outreach | follow_up | reply | pricing_objection | meeting_request | etc.
    content_preview TEXT,
    template_id TEXT,
    sentiment TEXT,                -- positive | neutral | negative
    outcome TEXT DEFAULT 'pending', -- pending | replied | ignored | meeting_booked | closed_won | closed_lost | unsubscribed
    time_to_reply_hours INTEGER,
    final_value_inr INTEGER,
    founder_feedback TEXT,
    evolution_rule_applied TEXT
);

CREATE INDEX IF NOT EXISTS idx_interactions_lead ON interactions(lead_id);
CREATE INDEX IF NOT EXISTS idx_interactions_timestamp ON interactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_interactions_outcome ON interactions(outcome);

-- ============================================
-- PENDING ACTIONS (Human Approval Queue)
-- ============================================
CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    action_type TEXT,              -- send_message | publish_content | update_lead | modify_rule
    description TEXT,
    payload TEXT,                  -- JSON
    urgency INTEGER DEFAULT 2,     -- 0-4
    approved_by TEXT,
    approved_at TIMESTAMP,
    rejected_reason TEXT,
    status TEXT DEFAULT 'pending'  -- pending | approved | rejected | expired
);

CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_actions(status);
CREATE INDEX IF NOT EXISTS idx_pending_urgency ON pending_actions(urgency);

-- ============================================
-- EVOLUTION RULES
-- ============================================
CREATE TABLE IF NOT EXISTS evolution_rules (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT,                   -- pattern_extractor | founder_feedback | manual
    confidence REAL,
    condition TEXT,
    action TEXT,
    priority TEXT DEFAULT 'medium', -- low | medium | high | critical
    expires_at TIMESTAMP,
    hit_count INTEGER DEFAULT 0,
    active BOOLEAN DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_rules_active ON evolution_rules(active);
CREATE INDEX IF NOT EXISTS idx_rules_priority ON evolution_rules(priority);

-- ============================================
-- COST TRACKING
-- ============================================
CREATE TABLE IF NOT EXISTS cost_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model TEXT,
    tokens_input INTEGER,
    tokens_output INTEGER,
    cost_usd REAL,
    task_type TEXT
);

CREATE INDEX IF NOT EXISTS idx_cost_timestamp ON cost_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_cost_month ON cost_log(strftime('%Y-%m', timestamp));

-- ============================================
-- USAGE VIEWS
-- ============================================
CREATE VIEW IF NOT EXISTS monthly_cost AS
SELECT 
    strftime('%Y-%m', timestamp) as month,
    SUM(cost_usd) as total_cost,
    SUM(tokens_input) as total_input_tokens,
    SUM(tokens_output) as total_output_tokens
FROM cost_log
GROUP BY month;

CREATE VIEW IF NOT EXISTS lead_pipeline AS
SELECT 
    status,
    COUNT(*) as count,
    AVG(priority) as avg_priority
FROM leads
GROUP BY status;

-- Insert seed data from JSON if available
-- (Populated separately via Python script)
