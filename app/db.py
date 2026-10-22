from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain import RawPaper


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self.connect() as connection:
            connection.executescript(schema)

    def get_app_settings(self) -> dict[str, str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT key, value FROM app_settings").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def set_app_settings(self, values: dict[str, str]) -> None:
        if not values:
            return
        now = _now_iso()
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO app_settings(key, value, updated_at) VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                [(key, str(value), now) for key, value in values.items()],
            )

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM app_users WHERE username=?",
                (username.strip(),),
            ).fetchone()
        return dict(row) if row else None

    def ensure_initial_admin(self, username: str, password_hash: str) -> None:
        now = _now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO app_users(username, password_hash, created_at, updated_at)
                SELECT ?, ?, ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM app_users)
                ON CONFLICT(username) DO NOTHING
                """,
                (username.strip(), password_hash, now, now),
            )

    def update_user_password(self, username: str, password_hash: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE app_users SET password_hash=?, updated_at=? WHERE username=?",
                (password_hash, _now_iso(), username.strip()),
            )
            updated = cursor.rowcount == 1
        return updated

    def upsert_venue(self, venue: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO venues(
                    slug, name, kind, tier, publisher, issns, homepage, topics, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    name=excluded.name,
                    kind=excluded.kind,
                    tier=excluded.tier,
                    publisher=excluded.publisher,
                    issns=excluded.issns,
                    homepage=excluded.homepage,
                    topics=excluded.topics,
                    updated_at=excluded.updated_at
                """,
                (
                    venue["slug"],
                    venue["name"],
                    venue["kind"],
                    venue["tier"],
                    venue.get("publisher", ""),
                    json.dumps(venue.get("issns", []), ensure_ascii=False),
                    venue.get("homepage", ""),
                    json.dumps(venue.get("topics", []), ensure_ascii=False),
                    _now_iso(),
                ),
            )

    def upsert_paper(self, paper: RawPaper) -> tuple[int, bool]:
        now = _now_iso()
        doi = _normalize_doi(paper.doi)
        title_key = _normalize_title(paper.title)
        source_key = f"doi:{doi}" if doi else f"title:{paper.venue_slug}:{title_key}"

        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM papers WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            if existing is None and not doi:
                existing = connection.execute(
                    """
                    SELECT id FROM papers
                    WHERE normalized_title = ? AND venue_slug = ?
                    ORDER BY id LIMIT 1
                    """,
                    (title_key, paper.venue_slug),
                ).fetchone()

            if existing:
                paper_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE papers SET
                        doi = CASE WHEN ? != '' THEN ? ELSE doi END,
                        title = CASE WHEN ? != '' THEN ? ELSE title END,
                        abstract = CASE WHEN ? != '' THEN ? ELSE abstract END,
                        authors = CASE WHEN ? != '[]' THEN ? ELSE authors END,
                        affiliations = CASE WHEN ? != '[]' THEN ? ELSE affiliations END,
                        venue_name = CASE WHEN ? != '' THEN ? ELSE venue_name END,
                        publisher = CASE WHEN ? != '' THEN ? ELSE publisher END,
                        published_date = CASE WHEN ? != '' THEN ? ELSE published_date END,
                        online_date = CASE WHEN ? != '' THEN ? ELSE online_date END,
                        url = CASE WHEN ? != '' THEN ? ELSE url END,
                        pdf_url = CASE WHEN ? != '' THEN ? ELSE pdf_url END,
                        is_oa = MAX(is_oa, ?),
                        cited_by_count = MAX(cited_by_count, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        doi,
                        doi,
                        paper.title,
                        paper.title,
                        paper.abstract,
                        paper.abstract,
                        json.dumps(paper.authors, ensure_ascii=False),
                        json.dumps(paper.authors, ensure_ascii=False),
                        json.dumps(paper.affiliations, ensure_ascii=False),
                        json.dumps(paper.affiliations, ensure_ascii=False),
                        paper.venue_name,
                        paper.venue_name,
                        paper.publisher,
                        paper.publisher,
                        paper.published_date,
                        paper.published_date,
                        paper.online_date,
                        paper.online_date,
                        paper.url,
                        paper.url,
                        paper.pdf_url,
                        paper.pdf_url,
                        int(paper.is_oa),
                        paper.cited_by_count,
                        now,
                        paper_id,
                    ),
                )
                is_new = False
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO papers(
                        source_key, doi, title, normalized_title, abstract, authors,
                        affiliations, venue_slug, venue_name, venue_kind, publisher,
                        published_date, online_date, url, pdf_url, is_oa, cited_by_count,
                        first_seen_at, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_key,
                        doi or None,
                        paper.title,
                        title_key,
                        paper.abstract,
                        json.dumps(paper.authors, ensure_ascii=False),
                        json.dumps(paper.affiliations, ensure_ascii=False),
                        paper.venue_slug,
                        paper.venue_name,
                        paper.venue_kind,
                        paper.publisher,
                        paper.published_date,
                        paper.online_date,
                        paper.url,
                        paper.pdf_url,
                        int(paper.is_oa),
                        paper.cited_by_count,
                        now,
                        now,
                        now,
                    ),
                )
                paper_id = int(cursor.lastrowid)
                is_new = True

            connection.execute(
                """
                INSERT OR REPLACE INTO paper_sources(paper_id, source, source_id, fetched_at)
                VALUES(?, ?, ?, ?)
                """,
                (paper_id, paper.source, paper.source_id, now),
            )
            return paper_id, is_new

    def record_citation(self, paper_id: int, cited_by_count: int, source: str) -> None:
        observed_date = datetime.now(UTC).date().isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO citation_snapshots(paper_id, observed_date, cited_by_count, source)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(paper_id, observed_date, source) DO UPDATE SET
                    cited_by_count=MAX(cited_by_count, excluded.cited_by_count)
                """,
                (paper_id, observed_date, max(0, cited_by_count), source),
            )
            connection.execute(
                "UPDATE papers SET cited_by_count=MAX(cited_by_count, ?), updated_at=? WHERE id=?",
                (max(0, cited_by_count), _now_iso(), paper_id),
            )

    def apply_enrichment(
        self,
        paper_id: int,
        *,
        abstract: str = "",
        cited_by_count: int | None = None,
        is_oa: bool | None = None,
        pdf_url: str = "",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE papers SET
                    abstract=CASE WHEN ? != '' THEN ? ELSE abstract END,
                    cited_by_count=CASE WHEN ? IS NOT NULL THEN MAX(cited_by_count, ?)
                                        ELSE cited_by_count END,
                    is_oa=CASE WHEN ? IS NOT NULL THEN MAX(is_oa, ?) ELSE is_oa END,
                    pdf_url=CASE WHEN ? != '' THEN ? ELSE pdf_url END,
                    updated_at=?
                WHERE id=?
                """,
                (
                    abstract,
                    abstract,
                    cited_by_count,
                    cited_by_count or 0,
                    None if is_oa is None else int(is_oa),
                    int(bool(is_oa)),
                    pdf_url,
                    pdf_url,
                    _now_iso(),
                    paper_id,
                ),
            )

    def get_recent_papers(self, days: int = 30, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM papers
                WHERE datetime(first_seen_at) >= datetime('now', ?)
                ORDER BY final_score DESC, first_seen_at DESC
                LIMIT ?
                """,
                (f"-{days} days", limit),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def get_papers_seen_since(self, since_iso: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM papers
                WHERE first_seen_at >= ?
                ORDER BY final_score DESC, first_seen_at DESC
                LIMIT ?
                """,
                (since_iso, limit),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def list_papers(
        self,
        query: str = "",
        venue: str = "",
        kind: str = "",
        days: int = 30,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["datetime(first_seen_at) >= datetime('now', ?)"]
        params: list[Any] = [f"-{days} days"]
        if query:
            clauses.append("(title LIKE ? OR abstract LIKE ? OR title_zh LIKE ?)")
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern])
        if venue:
            clauses.append("venue_slug = ?")
            params.append(venue)
        if kind:
            clauses.append("venue_kind = ?")
            params.append(kind)
        params.append(limit)
        sql = f"""
            SELECT * FROM papers
            WHERE {' AND '.join(clauses)}
            ORDER BY final_score DESC, first_seen_at DESC
            LIMIT ?
        """
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_decode_row(row) for row in rows]

    def get_paper(self, paper_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return _decode_row(row) if row else None

    def get_papers_by_ids(self, paper_ids: list[int]) -> list[dict[str, Any]]:
        if not paper_ids:
            return []
        placeholders = ",".join("?" for _ in paper_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM papers WHERE id IN ({placeholders})",
                paper_ids,
            ).fetchall()
        by_id = {int(row["id"]): _decode_row(row) for row in rows}
        return [by_id[paper_id] for paper_id in paper_ids if paper_id in by_id]

    def update_scores(
        self,
        paper_id: int,
        *,
        venue: float,
        relevance: float,
        novelty: float,
        momentum: float,
        openness: float,
        feedback: float,
        final: float,
        tags: list[str],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE papers SET
                    venue_score=?, relevance_score=?, novelty_score=?, momentum_score=?,
                    open_score=?, feedback_score=?, final_score=?, topic_tags=?, updated_at=?
                WHERE id=?
                """,
                (
                    venue,
                    relevance,
                    novelty,
                    momentum,
                    openness,
                    feedback,
                    final,
                    json.dumps(tags, ensure_ascii=False),
                    _now_iso(),
                    paper_id,
                ),
            )

    def save_summary(self, paper_id: int, summary: dict[str, Any], model: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE papers SET
                    title_zh=?, problem=?, method=?, key_results=?, limitations=?,
                    relevance_note=?, read_reason=?, novelty_score=?,
                    summary_status='complete', summary_model=?, updated_at=?
                WHERE id=?
                """,
                (
                    summary.get("title_zh", ""),
                    summary.get("problem", ""),
                    summary.get("method", ""),
                    summary.get("key_results", ""),
                    summary.get("limitations", ""),
                    summary.get("relevance", ""),
                    summary.get("read_reason", ""),
                    float(summary.get("novelty_score", 0.5)),
                    model,
                    _now_iso(),
                    paper_id,
                ),
            )

    def mark_summary_status(self, paper_id: int, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE papers SET summary_status=?, updated_at=? WHERE id=?",
                (status, _now_iso(), paper_id),
            )

    def set_feedback(self, paper_id: int, vote: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO feedback(paper_id, vote, updated_at) VALUES(?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    vote=excluded.vote,
                    updated_at=excluded.updated_at
                """,
                (paper_id, vote, _now_iso()),
            )

    def feedback_score(self, paper_id: int) -> float:
        mapping = {"important": 1.0, "neutral": 0.0, "ignore": -1.0}
        with self.connect() as connection:
            row = connection.execute(
                "SELECT vote FROM feedback WHERE paper_id=?",
                (paper_id,),
            ).fetchone()
        return mapping.get(row["vote"], 0.0) if row else 0.0

    def get_feedback(self, paper_id: int) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT vote FROM feedback WHERE paper_id=?",
                (paper_id,),
            ).fetchone()
        return row["vote"] if row else ""

    def create_report(
        self,
        *,
        kind: str,
        report_date: str,
        title: str,
        content_md: str,
        content_html: str,
        payload: dict[str, Any],
        markdown_path: str,
        html_path: str,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reports(
                    kind, report_date, title, content_md, content_html, payload_json,
                    markdown_path, html_path, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    report_date,
                    title,
                    content_md,
                    content_html,
                    json.dumps(payload, ensure_ascii=False),
                    markdown_path,
                    html_path,
                    _now_iso(),
                ),
            )
            return int(cursor.lastrowid)

    def list_reports(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reports ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def get_report(self, report_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        return _decode_row(row) if row else None

    def start_job(self, name: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO job_runs(job_name, status, started_at) VALUES(?, 'running', ?)",
                (name, _now_iso()),
            )
            return int(cursor.lastrowid)

    def finish_job(
        self,
        job_id: int,
        *,
        status: str,
        stats: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE job_runs SET status=?, finished_at=?, stats_json=?, error=? WHERE id=?
                """,
                (
                    status,
                    _now_iso(),
                    json.dumps(stats or {}, ensure_ascii=False),
                    error,
                    job_id,
                ),
            )

    def list_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def dashboard_stats(self) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS papers_30d,
                    SUM(CASE WHEN venue_kind='journal' THEN 1 ELSE 0 END) AS journal_30d,
                    SUM(CASE WHEN is_oa=1 THEN 1 ELSE 0 END) AS oa_30d,
                    SUM(CASE WHEN summary_status='complete' THEN 1 ELSE 0 END) AS summarized_30d
                FROM papers WHERE datetime(first_seen_at) >= datetime('now', '-30 days')
                """
            ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    def conference_source(self, venue_slug: str, url: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM conference_sources WHERE venue_slug=? AND url=?",
                (venue_slug, url),
            ).fetchone()
        return dict(row) if row else None

    def save_conference_snapshot(
        self,
        *,
        venue_slug: str,
        url: str,
        label: str,
        page_type: str,
        text: str,
        text_hash: str,
        etag: str,
        last_modified: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO conference_sources(
                    venue_slug, url, label, page_type, last_hash, last_text, etag,
                    last_modified, last_checked_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(venue_slug, url) DO UPDATE SET
                    label=excluded.label,
                    page_type=excluded.page_type,
                    last_hash=excluded.last_hash,
                    last_text=excluded.last_text,
                    etag=excluded.etag,
                    last_modified=excluded.last_modified,
                    last_checked_at=excluded.last_checked_at
                """,
                (
                    venue_slug,
                    url,
                    label,
                    page_type,
                    text_hash,
                    text,
                    etag,
                    last_modified,
                    _now_iso(),
                ),
            )

    def touch_conference_source(self, venue_slug: str, url: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE conference_sources SET last_checked_at=?
                WHERE venue_slug=? AND url=?
                """,
                (_now_iso(), venue_slug, url),
            )

    def add_conference_update(
        self,
        *,
        venue_slug: str,
        venue_name: str,
        url: str,
        label: str,
        page_type: str,
        title: str,
        excerpt: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO conference_updates(
                    venue_slug, venue_name, url, label, page_type, title, excerpt, detected_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    venue_slug,
                    venue_name,
                    url,
                    label,
                    page_type,
                    title,
                    excerpt,
                    _now_iso(),
                ),
            )

    def recent_conference_updates(self, days: int = 30, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conference_updates
                WHERE datetime(detected_at) >= datetime('now', ?)
                ORDER BY detected_at DESC LIMIT ?
                """,
                (f"-{days} days", limit),
            ).fetchall()
        return [dict(row) for row in rows]


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    decoded = dict(row)
    for field in (
        "authors",
        "affiliations",
        "topic_tags",
        "issns",
        "topics",
        "payload_json",
        "stats_json",
    ):
        if field in decoded and isinstance(decoded[field], str):
            try:
                decoded[field.removesuffix("_json")] = json.loads(decoded[field])
            except json.JSONDecodeError:
                decoded[field.removesuffix("_json")] = (
                    [] if field.endswith("s") or field == "topic_tags" else {}
                )
    return decoded


def _normalize_doi(value: str) -> str:
    doi = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi


def _normalize_title(value: str) -> str:
    import re

    return " ".join(re.findall(r"[\w\u4e00-\u9fff]+", value.lower()))

