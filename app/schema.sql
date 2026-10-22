PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS venues (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    tier INTEGER NOT NULL,
    publisher TEXT NOT NULL DEFAULT '',
    issns TEXT NOT NULL DEFAULT '[]',
    homepage TEXT NOT NULL DEFAULT '',
    topics TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    doi TEXT,
    title TEXT NOT NULL,
    title_zh TEXT NOT NULL DEFAULT '',
    normalized_title TEXT NOT NULL,
    abstract TEXT NOT NULL DEFAULT '',
    authors TEXT NOT NULL DEFAULT '[]',
    affiliations TEXT NOT NULL DEFAULT '[]',
    venue_slug TEXT NOT NULL,
    venue_name TEXT NOT NULL,
    venue_kind TEXT NOT NULL DEFAULT 'journal',
    publisher TEXT NOT NULL DEFAULT '',
    published_date TEXT NOT NULL DEFAULT '',
    online_date TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    pdf_url TEXT NOT NULL DEFAULT '',
    is_oa INTEGER NOT NULL DEFAULT 0,
    cited_by_count INTEGER NOT NULL DEFAULT 0,
    topic_tags TEXT NOT NULL DEFAULT '[]',
    venue_score REAL NOT NULL DEFAULT 0,
    relevance_score REAL NOT NULL DEFAULT 0,
    novelty_score REAL NOT NULL DEFAULT 0.5,
    momentum_score REAL NOT NULL DEFAULT 0.5,
    open_score REAL NOT NULL DEFAULT 0,
    feedback_score REAL NOT NULL DEFAULT 0,
    final_score REAL NOT NULL DEFAULT 0,
    summary_status TEXT NOT NULL DEFAULT 'pending',
    summary_model TEXT NOT NULL DEFAULT '',
    problem TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    key_results TEXT NOT NULL DEFAULT '',
    limitations TEXT NOT NULL DEFAULT '',
    relevance_note TEXT NOT NULL DEFAULT '',
    read_reason TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_papers_first_seen ON papers(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_papers_score ON papers(final_score DESC);
CREATE INDEX IF NOT EXISTS idx_papers_venue ON papers(venue_slug);
CREATE INDEX IF NOT EXISTS idx_papers_normalized_title ON papers(normalized_title);

CREATE TABLE IF NOT EXISTS paper_sources (
    paper_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (paper_id, source, source_id),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS citation_snapshots (
    paper_id INTEGER NOT NULL,
    observed_date TEXT NOT NULL,
    cited_by_count INTEGER NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (paper_id, observed_date, source),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback (
    paper_id INTEGER PRIMARY KEY,
    vote TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conference_sources (
    venue_slug TEXT NOT NULL,
    url TEXT NOT NULL,
    label TEXT NOT NULL,
    page_type TEXT NOT NULL,
    last_hash TEXT NOT NULL DEFAULT '',
    last_text TEXT NOT NULL DEFAULT '',
    etag TEXT NOT NULL DEFAULT '',
    last_modified TEXT NOT NULL DEFAULT '',
    last_checked_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (venue_slug, url)
);

CREATE TABLE IF NOT EXISTS conference_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_slug TEXT NOT NULL,
    venue_name TEXT NOT NULL,
    url TEXT NOT NULL,
    label TEXT NOT NULL,
    page_type TEXT NOT NULL,
    title TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    detected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conference_updates_detected
ON conference_updates(detected_at DESC);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    report_date TEXT NOT NULL,
    title TEXT NOT NULL,
    content_md TEXT NOT NULL,
    content_html TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    markdown_path TEXT NOT NULL DEFAULT '',
    html_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    stats_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_job_runs_started ON job_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

