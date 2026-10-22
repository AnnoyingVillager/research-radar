from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, urlsplit
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
from app.crypto import (
    SECRET_SETTING_FIELDS,
    delete_private_file,
    read_or_create_secret,
    rotate_secret,
)
from app.db import Database
from app.links import campus_url, doi_url
from app.llm import LLMService, normalize_llm_base_url

SESSION_COOKIE = "radar_session"
SETUP_PASSWORD_MIN_LENGTH = 12
SUMMARY_NOTICES = {
    "updated": ("AI 总结已更新。", True),
    "not_configured": ("未能生成总结：请先在系统设置中启用并配置 LLM。", False),
    "abstract_too_short": (
        "未能生成总结：原始摘要不足 120 个字符，无法可靠提炼。",
        False,
    ),
    "failed": ("未能生成总结：模型调用或响应解析失败，请检查日志后重试。", False),
}

settings = get_settings()
settings.ensure_directories()
database = Database(settings.database_path, settings_key_path=settings.settings_key_path)
venues = load_venues()
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
    _session_secret()
    if database.has_users():
        delete_private_file(settings.setup_token_path)
    else:
        read_or_create_secret(settings.setup_token_path, byte_count=32)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'; object-src 'none'; img-src 'self' data:"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), geolocation=(), microphone=()"
    )
    if request.url.path in {"/login", "/settings", "/setup"}:
        response.headers["Cache-Control"] = "no-store"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


def _runtime_settings() -> Settings:
    return get_runtime_settings(database, settings)


@lru_cache(maxsize=16)
def _load_session_secret(path: str) -> str:
    return read_or_create_secret(Path(path), byte_count=32)


def _session_secret() -> str:
    return _load_session_secret(str(settings.session_secret_path))


def _current_user(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    username = verify_session(token, _session_secret()) if token else None
    return username if username and database.get_user(username) else None


def _base_context(request: Request) -> dict[str, Any]:
    user = _current_user(request)
    return {
        "request": request,
        "app_name": settings.app_name,
        "current_user": user,
        "csrf_token": csrf_token(user, _session_secret()) if user else "",
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


def _require_user(
    request: Request,
    *,
    next_path: str | None = None,
) -> tuple[str | None, RedirectResponse | None]:
    username = _current_user(request)
    if username:
        return username, None
    if not database.has_users():
        return None, RedirectResponse(url="/setup", status_code=303)
    target = quote(next_path or request.url.path, safe="/")
    return None, RedirectResponse(url=f"/login?next={target}", status_code=303)


def _login_response(username: str, next_url: str) -> RedirectResponse:
    max_age = max(1, settings.session_max_age_hours) * 3600
    response = RedirectResponse(url=safe_next_url(next_url), status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session(username, _session_secret(), max_age),
        max_age=max_age,
        httponly=True,
        secure=settings.session_https_only or settings.tls_enabled,
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
                "llm_base_url": normalize_llm_base_url(runtime.llm_base_url),
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


def _setup_context(
    request: Request,
    *,
    error: str = "",
    username: str = "",
) -> dict[str, Any]:
    context = _base_context(request)
    context.update({"error": error, "username": username})
    return context


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    if database.has_users():
        target = "/" if _current_user(request) else "/login"
        return RedirectResponse(url=target, status_code=303)
    read_or_create_secret(settings.setup_token_path, byte_count=32)
    return templates.TemplateResponse(request, "setup.html", _setup_context(request))


@app.post("/setup", response_class=HTMLResponse)
async def setup_submit(request: Request):
    if database.has_users():
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    supplied_token = str(form.get("setup_token", "")).strip()
    expected_token = read_or_create_secret(settings.setup_token_path, byte_count=32)
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    confirm_password = str(form.get("confirm_password", ""))

    def render_error(message: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "setup.html",
            _setup_context(request, error=message, username=username),
            status_code=400,
        )

    if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
        return render_error("初始化令牌不正确。")
    if (
        not username
        or len(username) > 64
        or any(character.isspace() or ord(character) < 32 for character in username)
    ):
        return render_error("用户名需为 1 到 64 个字符，且不能包含空白或控制字符。")
    if len(password) < SETUP_PASSWORD_MIN_LENGTH:
        return render_error(f"管理员密码至少需要 {SETUP_PASSWORD_MIN_LENGTH} 个字符。")
    if password != confirm_password:
        return render_error("两次输入的密码不一致。")

    created = database.create_initial_admin(username, hash_password(password))
    if not created:
        delete_private_file(settings.setup_token_path)
        return RedirectResponse(url="/login", status_code=303)
    delete_private_file(settings.setup_token_path)
    return _login_response(username, "/settings")


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
async def paper_detail(
    request: Request,
    paper_id: int,
    summary: str = Query(default="", max_length=32),
):
    paper = database.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    context = _base_context(request)
    context["paper"] = _decorate_paper(paper, _runtime_settings())
    notice, success = SUMMARY_NOTICES.get(summary, ("", False))
    context["summary_notice"] = notice
    context["summary_notice_success"] = success
    return templates.TemplateResponse(request, "paper_detail.html", context)


@app.post("/papers/{paper_id}/summary")
async def update_paper_summary(request: Request, paper_id: int):
    username, redirect = _require_user(request, next_path=f"/papers/{paper_id}")
    if redirect:
        return redirect
    form = await request.form()
    if not valid_csrf(
        username or "",
        _session_secret(),
        str(form.get("csrf_token", "")),
    ):
        raise HTTPException(status_code=403, detail="无效请求")

    paper = database.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    if len((paper.get("abstract") or "").strip()) < 120:
        return RedirectResponse(
            url=f"/papers/{paper_id}?summary=abstract_too_short",
            status_code=303,
        )

    runtime = _runtime_settings()
    llm = LLMService(runtime)
    if not llm.configured:
        return RedirectResponse(
            url=f"/papers/{paper_id}?summary=not_configured",
            status_code=303,
        )

    summary = await llm.summarize(paper)
    if not summary:
        return RedirectResponse(
            url=f"/papers/{paper_id}?summary=failed",
            status_code=303,
        )
    database.save_summary(paper_id, summary, runtime.llm_model)
    return RedirectResponse(
        url=f"/papers/{paper_id}?summary=updated",
        status_code=303,
    )


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
    if not database.has_users():
        return RedirectResponse(url="/setup", status_code=303)
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
        _session_secret(),
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
        _session_secret(),
        str(form.get("csrf_token", "")),
    ):
        raise HTTPException(status_code=403, detail="无效请求")

    updates = {
        "openurl_base": str(form.get("openurl_base", "")).strip(),
        "openurl_doi_param": str(form.get("openurl_doi_param", "id=doi:")).strip(),
        "llm_enabled": _form_bool(form, "llm_enabled"),
        "llm_base_url": normalize_llm_base_url(
            str(form.get("llm_base_url", "")).strip()
        ),
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
    security_error = _validate_security_settings(updates, _runtime_settings())
    if security_error:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _settings_context(request, error=security_error),
            status_code=400,
        )

    password_error = ""
    if new_password or confirm_password:
        if new_password != confirm_password:
            password_error = "两次输入的新密码不一致。"
        elif len(new_password) < SETUP_PASSWORD_MIN_LENGTH:
            password_error = (
                f"新管理员密码至少需要 {SETUP_PASSWORD_MIN_LENGTH} 个字符。"
            )
    if password_error:
        return templates.TemplateResponse(
            request,
            "settings.html",
            _settings_context(request, error=password_error),
            status_code=400,
        )

    database.set_app_settings(updates)
    if new_password:
        if not database.update_user_password(username or "", hash_password(new_password)):
            raise HTTPException(status_code=500, detail="无法更新管理员密码")
        rotate_secret(settings.session_secret_path, byte_count=32)
        _load_session_secret.cache_clear()
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response
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


def _validate_security_settings(values: dict[str, str], runtime: Settings) -> str:
    llm_base_url = values.get("llm_base_url", runtime.llm_base_url).strip()
    llm_api_key = values.get("llm_api_key", runtime.llm_api_key)
    openurl_base = values.get("openurl_base", runtime.openurl_base).strip()

    openurl_error = _validate_http_url(openurl_base, "OpenURL 基础地址")
    if openurl_error:
        return openurl_error

    llm_error = _validate_http_url(llm_base_url, "LLM 接口基础地址")
    if llm_error:
        return llm_error
    if llm_base_url:
        parsed_llm = urlsplit(llm_base_url)
        if parsed_llm.query or parsed_llm.fragment:
            return "LLM 接口基础地址不能包含查询参数或片段。"
        if llm_api_key and parsed_llm.scheme != "https":
            return "配置 LLM API Key 时，接口地址必须使用 HTTPS。"

    smtp_ssl = _effective_bool(values, runtime, "smtp_ssl")
    smtp_starttls = _effective_bool(values, runtime, "smtp_starttls")
    smtp_username = values.get("smtp_username", runtime.smtp_username).strip()
    smtp_password = values.get("smtp_password", runtime.smtp_password)
    if smtp_ssl and smtp_starttls:
        return "SMTP 的 SSL 和 STARTTLS 只能启用一种。"
    if bool(smtp_username) != bool(smtp_password):
        return "SMTP 用户名和密码必须同时配置，或同时留空。"
    if (smtp_username or smtp_password) and not (smtp_ssl or smtp_starttls):
        return "配置 SMTP 凭据时必须启用 SSL 或 STARTTLS。"
    smtp_host = values.get("smtp_host", runtime.smtp_host).strip()
    if smtp_host and not (smtp_ssl or smtp_starttls):
        return "启用 SMTP 时必须使用 SSL 或 STARTTLS，以免邮件明文传输。"
    return ""


def _effective_bool(values: dict[str, str], runtime: Settings, field: str) -> bool:
    value = values.get(field)
    if value is None:
        return bool(getattr(runtime, field))
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _validate_http_url(value: str, label: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return f"{label}必须是有效的 HTTP 或 HTTPS 地址。"
    if parsed.username or parsed.password:
        return f"{label}不能包含用户名或密码。"
    return ""


@app.get("/health")
async def health():
    database.has_users()
    return JSONResponse({"status": "ok"})
