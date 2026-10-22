from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.db import Database
from app.pipeline import DailyPipeline, generate_weekly

logger = logging.getLogger(__name__)


async def run_scheduler(database: Database, settings: Settings) -> None:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.app_timezone))

    async def daily_job() -> None:
        await DailyPipeline(database, settings).run(generate_report=True)

    async def weekly_job() -> None:
        await generate_weekly(database, settings)

    scheduler.add_job(
        daily_job,
        CronTrigger(
            hour=settings.daily_run_hour,
            minute=settings.daily_run_minute,
            timezone=ZoneInfo(settings.app_timezone),
        ),
        id="daily-radar",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        weekly_job,
        CronTrigger(
            day_of_week=settings.weekly_run_day,
            hour=settings.weekly_run_hour,
            minute=settings.weekly_run_minute,
            timezone=ZoneInfo(settings.app_timezone),
        ),
        id="weekly-radar",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=7200,
    )
    scheduler.start()
    logger.info("scheduler started at %s", datetime.now(ZoneInfo(settings.app_timezone)))
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)

