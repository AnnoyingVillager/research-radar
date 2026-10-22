from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings, load_venues
from app.db import Database
from app.links import campus_url, doi_url

settings = get_settings()
settings.ensure_directories()
database = Database(settings.database_path)
venues = load_venues()
venues_by_slug = venues.by_slug()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _format_score(value: float | None) -> str:
    return f"{round(float(value or 0) * 100)}"


def _format_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(ZoneInfo(settings.app_timezone)).strftime("%m-%d %H:%M")
    except ValueError:
        return value[:16]


templates.env.filters["score"] = _format_score
templates.env.filters["datetime_cn"] = _format_datetime


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init()
    for venue in venues.all:
        database.upsert_venue(venue.model_dump(mode="json"))
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def _decorate_paper(paper: dict) -> dict:
    value = dict(paper)
    value["authors_text"] = "、".join(value.get("authors", [])[:8])
    value["campus_url"] = campus_url(value.get("doi") or "", settings)
    value["doi_url"] = doi_url(value.get("doi") or "")
    value["display_date"] = (
        value.get("online_date")
        or value.get("published_date")
        or value.get("first_seen_at", "")[:10]
    )
    value["feedback"] = database.get_feedback(int(value["id"]))
    return value


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    q: str = Query(default="", max_length=200),
    venue: str = Query(default="", max_length=80),
    kind: str = Query(default="", max_length=20),
    days: int = Query(default=30, ge=1, le=365),
):
    papers = database.list_papers(query=q, venue=venue, kind=kind, days=days, limit=100)
    latest_reports = database.list_reports(limit=5)
    jobs = database.list_jobs(limit=5)
    conference_updates = database.recent_conference_updates(days=30, limit=12)
    context = {
        "request": request,
        "app_name": settings.app_name,
        "now": datetime.now(ZoneInfo(settings.app_timezone)),
        "stats": database.dashboard_stats(),
        "papers": [_decorate_paper(paper) for paper in papers],
        "latest_report": latest_reports[0] if latest_reports else None,
        "jobs": jobs,
        "conference_updates": conference_updates,
        "journals": venues.journals,
        "filters": {"q": q, "venue": venue, "kind": kind, "days": days},
    }
    return templates.TemplateResponse(request, "dashboard.html", context)


@app.get("/papers/{paper_id}", response_class=HTMLResponse)
async def paper_detail(request: Request, paper_id: int):
    paper = database.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    context = {
        "request": request,
        "app_name": settings.app_name,
        "paper": _decorate_paper(paper),
    }
    return templates.TemplateResponse(request, "paper_detail.html", context)


@app.post("/papers/{paper_id}/feedback")
async def submit_feedback(
    paper_id: int,
    vote: Annotated[str, Form()],
):
    if vote not in {"important", "neutral", "ignore"}:
        raise HTTPException(status_code=400, detail="无效反馈")
    if not database.get_paper(paper_id):
        raise HTTPException(status_code=404, detail="论文不存在")
    database.set_feedback(paper_id, vote)
    return RedirectResponse(url=f"/papers/{paper_id}", status_code=303)


@app.get("/reports", response_class=HTMLResponse)
async def reports(request: Request):
    context = {
        "request": request,
        "app_name": settings.app_name,
        "reports": database.list_reports(limit=100),
    }
    return templates.TemplateResponse(request, "reports.html", context)


@app.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(request: Request, report_id: int):
    report = database.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    context = {
        "request": request,
        "app_name": settings.app_name,
        "report": report,
    }
    return templates.TemplateResponse(request, "report.html", context)


@app.get("/health")
async def health():
    jobs = database.list_jobs(limit=20)
    last_success = next((job for job in jobs if job.get("status") == "success"), None)
    latest = jobs[0] if jobs else None
    return JSONResponse(
        {
            "status": "ok",
            "database": str(settings.database_path),
            "latest_job": latest,
            "last_success": last_success,
        }
    )

