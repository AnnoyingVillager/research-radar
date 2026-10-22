from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import Settings, VenuesConfig
from app.db import Database
from app.links import campus_url
from app.notify import EmailNotifier


class ReportService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        venues: VenuesConfig,
    ):
        self.database = database
        self.settings = settings
        self.venues = venues
        templates = Path(__file__).parent / "templates"
        self.environment = Environment(
            loader=FileSystemLoader(templates),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.environment.filters["score"] = _format_score
        self.body_template = self.environment.get_template("report_body.html")

    async def generate_daily(
        self,
        *,
        hours: int = 30,
        warnings: list[str] | None = None,
        notify: bool = True,
    ) -> int:
        now_local = datetime.now(ZoneInfo(self.settings.app_timezone))
        since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        papers = self.database.get_papers_seen_since(since, limit=500)
        return await self._generate(
            kind="daily",
            title=f"{now_local:%Y-%m-%d} 科研雷达日报",
            papers=papers,
            warnings=warnings or [],
            report_date=now_local.date().isoformat(),
            notify=notify,
        )

    async def generate_weekly(self, *, notify: bool = True) -> int:
        now_local = datetime.now(ZoneInfo(self.settings.app_timezone))
        papers = self.database.get_recent_papers(days=7, limit=500)
        return await self._generate(
            kind="weekly",
            title=f"{now_local:%Y-%m-%d} 科研雷达周报",
            papers=papers,
            warnings=[],
            report_date=now_local.date().isoformat(),
            notify=notify,
        )

    async def _generate(
        self,
        *,
        kind: str,
        title: str,
        papers: list[dict[str, Any]],
        warnings: list[str],
        report_date: str,
        notify: bool,
    ) -> int:
        prepared = [self._prepare_paper(paper) for paper in papers]
        sections = {
            "气动声学": _filter_tag(prepared, "气动声学"),
            "流体力学": _filter_tag(prepared, "流体力学"),
            "计算方法": _filter_tag(prepared, "计算方法"),
        }
        top = prepared[:10]
        conference_updates = self.database.recent_conference_updates(days=14, limit=20)
        context = {
            "title": title,
            "kind": kind,
            "top": top,
            "sections": sections,
            "papers": prepared,
            "conference_updates": conference_updates,
            "warnings": warnings,
        }
        content_html = self.body_template.render(**context)
        content_md = self._render_markdown(
            title=title,
            top=top,
            sections=sections,
            conference_updates=conference_updates,
            warnings=warnings,
        )

        stem = f"{report_date}-{kind}"
        markdown_path = self.settings.reports_dir / f"{stem}.md"
        html_path = self.settings.reports_dir / f"{stem}.html"
        markdown_path.write_text(content_md, encoding="utf-8")
        html_path.write_text(_standalone_html(title, content_html), encoding="utf-8")
        payload = {
            "paper_ids": [paper["id"] for paper in prepared],
            "warnings": warnings,
        }
        report_id = self.database.create_report(
            kind=kind,
            report_date=report_date,
            title=title,
            content_md=content_md,
            content_html=content_html,
            payload=payload,
            markdown_path=str(markdown_path),
            html_path=str(html_path),
        )
        if notify:
            notifier = EmailNotifier(self.settings)
            if notifier.configured:
                await notifier.send(title, _standalone_html(title, content_html), content_md)
        return report_id

    def _prepare_paper(self, paper: dict[str, Any]) -> dict[str, Any]:
        value = dict(paper)
        value["authors_text"] = "、".join(value.get("authors", [])[:8])
        value["doi"] = value.get("doi") or ""
        value["campus_url"] = campus_url(value["doi"], self.settings)
        value["score_percent"] = round(float(value.get("final_score", 0)) * 100)
        value["abstract_excerpt"] = (value.get("abstract") or "")[:900]
        value["display_date"] = (
            value.get("online_date")
            or value.get("published_date")
            or value.get("first_seen_at", "")[:10]
        )
        return value

    def _render_markdown(
        self,
        *,
        title: str,
        top: list[dict[str, Any]],
        sections: dict[str, list[dict[str, Any]]],
        conference_updates: list[dict[str, Any]],
        warnings: list[str],
    ) -> str:
        lines = [f"# {title}", ""]
        lines.append("## 今日最值得关注")
        if top:
            lines.extend(_markdown_paper(paper) for paper in top)
        else:
            lines.append("当前时间窗口内没有新增论文。")

        for label, values in sections.items():
            lines.extend(["", f"## {label}"])
            if values:
                lines.extend(_markdown_paper(paper, compact=True) for paper in values[:12])
            else:
                lines.append("暂无新增。")

        lines.extend(["", "## 会议动态"])
        if conference_updates:
            for update in conference_updates[:12]:
                lines.append(
                    f"- [{update['venue_name']} / {update['label']}]({update['url']})："
                    f"{update['excerpt'][:300]}"
                )
        else:
            lines.append("暂无会议页面变更。")

        if warnings:
            lines.extend(["", "## 采集警告"])
            lines.extend(f"- {warning}" for warning in warnings)
        return "\n".join(lines).strip() + "\n"


def _filter_tag(papers: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    return [paper for paper in papers if label in paper.get("topic_tags", [])]


def _format_score(value: float | None) -> str:
    return str(round(float(value or 0) * 100))


def _markdown_paper(paper: dict[str, Any], compact: bool = False) -> str:
    title = paper.get("title_zh") or paper.get("title")
    link = paper.get("campus_url") or paper.get("url")
    line = f"- **[{title}]({link})**，{paper.get('venue_name')}，{paper.get('display_date')}"
    if not compact and paper.get("read_reason"):
        line += f"\n  - 阅读理由：{paper['read_reason']}"
    if not compact and paper.get("method"):
        line += f"\n  - 方法：{paper['method']}"
    return line


def _standalone_html(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body class="report-document"><main class="container">{body}</main></body>
</html>"""

