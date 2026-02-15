-- Augustus Database Schema v0.2
-- SQLite DDL for all structured storage

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Agent Registry
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'idle',
    config_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    last_active TEXT DEFAULT ''
);

-- Session Records
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT DEFAULT '',
    turn_count INTEGER DEFAULT 0,
    model TEXT DEFAULT '',
    temperature REAL DEFAULT 1.0,
    transcript_json TEXT DEFAULT '[]',
    close_report_json TEXT DEFAULT '{}',
    yaml_raw TEXT DEFAULT '',
    status TEXT DEFAULT 'complete',
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
);

-- Basin Snapshots (per-session trajectories)
CREATE TABLE IF NOT EXISTS basin_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    basin_name TEXT NOT NULL,
    alpha_start REAL NOT NULL,
    alpha_end REAL NOT NULL,
    delta REAL NOT NULL,
    relevance_score REAL DEFAULT 0.0,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

-- Basin Current State (latest alpha values per agent)
CREATE TABLE IF NOT EXISTS basin_current (
    agent_id TEXT NOT NULL,
    basin_name TEXT NOT NULL,
    basin_class TEXT NOT NULL,
    alpha REAL NOT NULL,
    lambda REAL NOT NULL,
    eta REAL NOT NULL,
    tier INTEGER NOT NULL DEFAULT 3,
    PRIMARY KEY (agent_id, basin_name),
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
);

-- Tier Proposals
CREATE TABLE IF NOT EXISTS tier_proposals (
    proposal_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    basin_name TEXT NOT NULL,
    tier INTEGER NOT NULL,
    proposal_type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    rationale TEXT DEFAULT '',
    session_id TEXT DEFAULT '',
    consecutive_count INTEGER DEFAULT 0,
    proposed_config_json TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT DEFAULT '',
    resolved_by TEXT DEFAULT '',
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
);

-- Evaluator Outputs
CREATE TABLE IF NOT EXISTS evaluator_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    output_json TEXT NOT NULL,
    prompt_version TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

-- Evaluator Prompt Versions
CREATE TABLE IF NOT EXISTS evaluator_prompts (
    version_id TEXT PRIMARY KEY,
    prompt_text TEXT NOT NULL,
    change_rationale TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 0
);

-- Human Annotations
CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    session_id TEXT DEFAULT '',
    content TEXT DEFAULT '',
    tags_json TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
);

-- Evaluator Flags
CREATE TABLE IF NOT EXISTS flags (
    flag_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    session_id TEXT DEFAULT '',
    flag_type TEXT NOT NULL,
    severity TEXT DEFAULT 'info',
    detail TEXT DEFAULT '',
    reviewed INTEGER DEFAULT 0,
    review_note TEXT DEFAULT '',
    reviewed_at TEXT DEFAULT '',
    reviewed_by TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
);

-- Co-Activation Log
CREATE TABLE IF NOT EXISTS co_activation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    basin_a TEXT NOT NULL,
    basin_b TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    character TEXT DEFAULT 'uncharacterized',
    last_session_id TEXT DEFAULT '',
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
);

-- Usage Tracking
-- NOTE: No foreign keys — usage records must survive both agent AND session deletion
-- so billing data is always preserved.
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    estimated_cost REAL DEFAULT 0.0,
    model TEXT DEFAULT '',
    timestamp TEXT DEFAULT (datetime('now'))
);

-- Activity Feed
CREATE TABLE IF NOT EXISTS activity_feed (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    agent_id TEXT DEFAULT '',
    session_id TEXT DEFAULT '',
    detail TEXT DEFAULT '',
    timestamp TEXT DEFAULT (datetime('now'))
);

-- Indexes for efficient queries

-- Sessions
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_start_time ON sessions(start_time);

-- Basin Snapshots
CREATE INDEX IF NOT EXISTS idx_basin_snapshots_agent ON basin_snapshots(agent_id);
CREATE INDEX IF NOT EXISTS idx_basin_snapshots_session ON basin_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_basin_snapshots_agent_basin ON basin_snapshots(agent_id, basin_name);

-- Tier Proposals
CREATE INDEX IF NOT EXISTS idx_tier_proposals_agent ON tier_proposals(agent_id);
CREATE INDEX IF NOT EXISTS idx_tier_proposals_status ON tier_proposals(status);
CREATE INDEX IF NOT EXISTS idx_tier_proposals_agent_basin ON tier_proposals(agent_id, basin_name);

-- Flags
CREATE INDEX IF NOT EXISTS idx_flags_agent ON flags(agent_id);
CREATE INDEX IF NOT EXISTS idx_flags_session ON flags(session_id);
CREATE INDEX IF NOT EXISTS idx_flags_reviewed ON flags(reviewed);
CREATE INDEX IF NOT EXISTS idx_flags_type ON flags(flag_type);

-- Annotations
CREATE INDEX IF NOT EXISTS idx_annotations_agent ON annotations(agent_id);
CREATE INDEX IF NOT EXISTS idx_annotations_session ON annotations(session_id);

-- Usage
CREATE INDEX IF NOT EXISTS idx_usage_agent ON usage(agent_id);
CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_session ON usage(session_id);

-- Activity Feed
CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity_feed(timestamp);
CREATE INDEX IF NOT EXISTS idx_activity_type ON activity_feed(event_type);
CREATE INDEX IF NOT EXISTS idx_activity_agent ON activity_feed(agent_id);

-- Co-Activation
CREATE INDEX IF NOT EXISTS idx_co_activation_agent ON co_activation_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_co_activation_basins ON co_activation_log(agent_id, basin_a, basin_b);

-- Evaluator Outputs
CREATE INDEX IF NOT EXISTS idx_evaluator_outputs_session ON evaluator_outputs(session_id);

-- Evaluator Prompts
CREATE INDEX IF NOT EXISTS idx_evaluator_prompts_active ON evaluator_prompts(is_active);
