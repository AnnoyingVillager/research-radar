from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import (
    create_session,
    csrf_token,
    hash_password,
    safe_next_url,
    valid_csrf,
    verify_password,
    verify_session,
)
from app.config import Settings, get_runtime_settings, get_settings, load_venues
from app.db import Database
from app.links import campus_url, doi_url

SESSION_COOKIE = "radar_session"
SECRET_SETTING_FIELDS = ("openalex_api_key", "llm_api_key", "smtp_password")

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
    database.ensure_initial_admin(
        settings.admin_username,
        hash_password(settings.admin_password),
    )
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def _runtime_settings() -> Settings:
    return get_runtime_settings(database, settings)


def _current_user(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    return verify_session(token, settings.session_secret) if token else None


def _base_context(request: Request) -> dict[str, Any]:
    user = _current_user(request)
    return {
        "request": request,
        "app_name": settings.app_name,
        "current_user": user,
        "csrf_token": csrf_token(user, settings.session_secret) if user else "",
    }


def _decorate_paper(paper: dict, runtime: Settings) -> dict:
    value = dict(paper)
    value["authors_text"] = "、".join(value.get("authors", [])[:8])
    value["campus_url"] = campus_url(value.get("doi") or "", runtime)
    value["doi_url"] = doi_url(value.get("doi") or "")
    value["display_date"] = (
        value.get("online_date")
        or value.get("published_date")
        or value.get("first_seen_at", "")[:10]
    )
    value["feedback"] = database.get_feedback(int(value["id"]))
    return value


def _require_user(request: Request) -> tuple[str | None, RedirectResponse | None]:
    username = _current_user(request)
    if username:
        return username, None
    target = quote(request.url.path, safe="/")
    return None, RedirectResponse(url=f"/login?next={target}", status_code=303)


def _login_response(username: str, next_url: str) -> RedirectResponse:
    max_age = max(1, settings.session_max_age_hours) * 3600
    response = RedirectResponse(url=safe_next_url(next_url), status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session(username, settings.session_secret, max_age),
        max_age=max_age,
        httponly=True,
        secure=settings.session_https_only,
        samesite="lax",
        path="/",
    )
    return response


def _settings_context(
    request: Request,
    *,
    error: str = "",
    saved: bool = False,
) -> dict[str, Any]:
    runtime = _runtime_settings()
    context = _base_context(request)
    context.update(
        {
            "error": error,
            "saved": saved,
            "values": {
                "openalex_api_key": "",
                "openurl_base": runtime.openurl_base,
                "openurl_doi_param": runtime.openurl_doi_param,
                "llm_enabled": runtime.llm_enabled,
                "llm_base_url": runtime.llm_base_url,
                "llm_api_key": "",
                "llm_model": runtime.llm_model,
                "summary_limit": runtime.summary_limit,
                "smtp_host": runtime.smtp_host,
                "smtp_port": runtime.smtp_port,
                "smtp_username": runtime.smtp_username,
                "smtp_password": "",
                "smtp_from": runtime.smtp_from,
                "smtp_to": runtime.smtp_to,
                "smtp_starttls": runtime.smtp_starttls,
                "smtp_ssl": runtime.smtp_ssl,
            },
            "secret_configured": {
                field: bool(getattr(runtime, field)) for field in SECRET_SETTING_FIELDS
            },
        }
    )
    return context


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    q: str = Query(default="", max_length=200),
    venue: str = Query(default="", max_length=80),
    kind: str = Query(default="", max_length=20),
    days: int = Query(default=30, ge=1, le=365),
):
    runtime = _runtime_settings()
    papers = database.list_papers(query=q, venue=venue, kind=kind, days=days, limit=100)
    latest_reports = database.list_reports(limit=5)
    jobs = database.list_jobs(limit=5)
    conference_updates = database.recent_conference_updates(days=30, limit=12)
    context = _base_context(request)
    context.update(
        {
            "now": datetime.now(ZoneInfo(runtime.app_timezone)),
            "stats": database.dashboard_stats(),
            "papers": [_decorate_paper(paper, runtime) for paper in papers],
            "latest_report": latest_reports[0] if latest_reports else None,
            "jobs": jobs,
            "conference_updates": conference_updates,
            "journals": venues.journals,
            "filters": {"q": q, "venue": venue, "kind": kind, "days": days},
        }
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@app.get("/papers/{paper_id}", response_class=HTMLResponse)
async def paper_detail(request: Request, paper_id: int):
    paper = database.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    context = _base_context(request)
    context["paper"] = _decorate_paper(paper, _runtime_settings())
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
    context = _base_context(request)
    context["reports"] = database.list_reports(limit=100)
    return templates.TemplateResponse(request, "reports.html", context)


@app.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(request: Request, report_id: int):
    report = database.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    context = _base_context(request)
    context["report"] = report
    return templates.TemplateResponse(request, "report.html", context)


@app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next_url: str = Query(default="/settings", alias="next"),
):
    if _current_user(request):
        return RedirectResponse(url=safe_next_url(next_url), status_code=303)
    context = _base_context(request)
    context.update({"next_url": safe_next_url(next_url), "error": ""})
    return templates.TemplateResponse(request, "login.html", context)


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    next_url = safe_next_url(str(form.get("next", "/settings")))
    user = database.get_user(username)
    if user and verify_password(password, str(user["password_hash"])):
        return _login_response(str(user["username"]), next_url)
    context = _base_context(request)
    context.update(
        {
            "next_url": next_url,
            "error": "用户名或密码不正确。",
            "username": username,
        }
    )
    return templates.TemplateResponse(
        request,
        "login.html",
        context,
        status_code=400,
    )


@app.post("/logout")
async def logout(request: Request):
    form = await request.form()
    username, redirect = _require_user(request)
    if redirect:
        return redirect
    if not valid_csrf(
        username or "",
        settings.session_secret,
        str(form.get("csrf_token", "")),
    ):
        raise HTTPException(status_code=403, detail="无效请求")
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: int = Query(default=0)):
    username, redirect = _require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "settings.html",
        _settings_context(request, saved=bool(saved)),
    )


@app.post("/settings", response_class=HTMLResponse)
async def save_settings(request: Request):
    username, redirect = _require_user(request)
    if redirect:
        return redirect
    form = await request.form()
    if not valid_csrf(
        username or "",
        settings.session_secret,
        str(form.get("csrf_token", "")),
    ):
        raise HTTPException(status_code=403, detail="无效请求")

    updates = {
        "openurl_base": str(form.get("openurl_base", "")).strip(),
        "openurl_doi_param": str(form.get("openurl_doi_param", "id=doi:")).strip(),
        "llm_enabled": _form_bool(form, "llm_enabled"),
        "llm_base_url": str(form.get("llm_base_url", "")).strip(),
        "llm_model": str(form.get("llm_model", "")).strip(),
        "summary_limit": str(form.get("summary_limit", "30")).strip(),
        "smtp_host": str(form.get("smtp_host", "")).strip(),
        "smtp_port": str(form.get("smtp_port", "587")).strip(),
        "smtp_username": str(form.get("smtp_username", "")).strip(),
        "smtp_from": str(form.get("smtp_from", "")).strip(),
        "smtp_to": str(form.get("smtp_to", "")).strip(),
        "smtp_starttls": _form_bool(form, "smtp_starttls"),
        "smtp_ssl": _form_bool(form, "smtp_ssl"),
    }
    error = _validate_numeric_settings(updates)
    if error:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _settings_context(request, error=error),
            status_code=400,
        )

    for field in SECRET_SETTING_FIELDS:
        supplied = str(form.get(field, "")).strip()
        if supplied:
            updates[field] = supplied
        elif _form_bool(form, f"clear_{field}"):
            updates[field] = ""

    new_password = str(form.get("new_password", ""))
    confirm_password = str(form.get("confirm_password", ""))
    if new_password or confirm_password:
        if new_password != confirm_password:
            error = "两次输入的新密码不一致。"
        elif len(new_password) < 10:
            error = "新管理员密码至少需要 10 个字符。"
        if error:
            return templates.TemplateResponse(
                request,
                "settings.html",
                _settings_context(request, error=error),
                status_code=400,
            )
        database.update_user_password(username or "", hash_password(new_password))

    database.set_app_settings(updates)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


def _form_bool(form: Any, field: str) -> str:
    return "true" if str(form.get(field, "")).lower() in {"1", "true", "on", "yes"} else "false"


def _validate_numeric_settings(values: dict[str, str]) -> str:
    try:
        summary_limit = int(values["summary_limit"])
        smtp_port = int(values["smtp_port"])
    except ValueError:
        return "总结条数和 SMTP 端口必须是整数。"
    if not 1 <= summary_limit <= 200:
        return "单次总结论文数应在 1 到 200 之间。"
    if not 1 <= smtp_port <= 65535:
        return "SMTP 端口应在 1 到 65535 之间。"
    return ""


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
