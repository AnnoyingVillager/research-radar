from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from app.db import Database


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "科研雷达"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_timezone: str = "Asia/Shanghai"
    admin_username: str = "admin"
    admin_password: str = "change-this-admin-password"
    session_secret: str = "change-this-session-secret"
    session_max_age_hours: int = 168
    session_https_only: bool = False
    daily_run_hour: int = 6
    daily_run_minute: int = 50
    weekly_run_day: str = "sat"
    weekly_run_hour: int = 8
    weekly_run_minute: int = 0

    config_dir: Path = Path("config")
    data_dir: Path = Path("data")
    logs_dir: Path = Path("logs")
    cache_dir: Path = Path("cache")
    papers_dir: Path = Path("papers")

    crossref_email: str = "research@example.edu"
    user_agent: str = "ResearchRadar/0.1 (mailto:research@example.edu)"
    openalex_mailto: str = "research@example.edu"
    openalex_api_key: str = ""

    openurl_base: str = ""
    openurl_doi_param: str = "id=doi:"

    llm_enabled: bool = False
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    summary_limit: int = 30

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False

    @property
    def database_path(self) -> Path:
        return self.data_dir / "radar.db"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.reports_dir,
            self.logs_dir,
            self.cache_dir,
            self.papers_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


DATABASE_SETTING_FIELDS = (
    "openalex_api_key",
    "openurl_base",
    "openurl_doi_param",
    "llm_enabled",
    "llm_base_url",
    "llm_api_key",
    "llm_model",
    "summary_limit",
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_password",
    "smtp_from",
    "smtp_to",
    "smtp_starttls",
    "smtp_ssl",
)


def apply_database_settings(
    base: Settings,
    values: Mapping[str, Any],
) -> Settings:
    """Apply validated web-managed settings on top of environment defaults."""
    updates: dict[str, Any] = {}
    for field in DATABASE_SETTING_FIELDS:
        if field not in values:
            continue
        raw = values[field]
        if field in {"llm_enabled", "smtp_starttls", "smtp_ssl"}:
            updates[field] = _parse_bool(raw)
        elif field in {"summary_limit", "smtp_port"}:
            try:
                updates[field] = int(raw)
            except (TypeError, ValueError):
                continue
        else:
            updates[field] = str(raw)
    return base.model_copy(update=updates)


def get_runtime_settings(database: Database, base: Settings | None = None) -> Settings:
    source = base or get_settings()
    return apply_database_settings(source, database.get_app_settings())


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class InterestGroup(BaseModel):
    label: str
    weight: float = Field(default=1.0, ge=0, le=2)
    keywords: list[str]


class InterestProfile(BaseModel):
    title: str
    description: str = ""
    language: str = "zh-CN"


class InterestsConfig(BaseModel):
    profile: InterestProfile
    groups: list[InterestGroup]
    negative_keywords: list[str] = Field(default_factory=list)


class ConferencePage(BaseModel):
    label: str
    type: str
    url: HttpUrl


class Venue(BaseModel):
    slug: str
    name: str
    kind: str
    tier: int = Field(default=2, ge=1, le=3)
    publisher: str = ""
    issns: list[str] = Field(default_factory=list)
    homepage: HttpUrl
    rss: list[HttpUrl] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    pages: list[ConferencePage] = Field(default_factory=list)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in {"journal", "conference"}:
            raise ValueError("venue kind must be journal or conference")
        return value

    @field_validator("issns")
    @classmethod
    def normalize_issns(cls, values: list[str]) -> list[str]:
        return [value.strip().upper() for value in values]


class VenuesConfig(BaseModel):
    journals: list[Venue]
    conferences: list[Venue]

    @property
    def all(self) -> list[Venue]:
        return [*self.journals, *self.conferences]

    def by_slug(self) -> dict[str, Venue]:
        return {venue.slug: venue for venue in self.all}


class SourcePolicy(BaseModel):
    enabled: bool = True
    request_delay_seconds: float = 1.0
    lookback_days: int = 14
    rows_per_journal: int = 100
    max_retries: int = 2
    max_entries_per_feed: int = 100
    batch_size: int = 10
    enrich_limit: int = 50
    max_text_chars: int = 200000


class SourcesConfig(BaseModel):
    crossref: SourcePolicy
    rss: SourcePolicy
    openalex: SourcePolicy
    conference: SourcePolicy
    http: dict[str, int | float]


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_interests(path: Path | None = None) -> InterestsConfig:
    source = path or get_settings().config_dir / "interests.yaml"
    return InterestsConfig.model_validate(_load_yaml(source))


def load_venues(path: Path | None = None) -> VenuesConfig:
    source = path or get_settings().config_dir / "venues.yaml"
    config = VenuesConfig.model_validate(_load_yaml(source))
    slugs = [venue.slug for venue in config.all]
    if len(slugs) != len(set(slugs)):
        raise ValueError("venue slugs must be unique")
    return config


def load_sources(path: Path | None = None) -> SourcesConfig:
    source = path or get_settings().config_dir / "sources.yaml"
    return SourcesConfig.model_validate(_load_yaml(source))

