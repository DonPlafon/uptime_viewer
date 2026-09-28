import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from sqlalchemy import delete, select

from database import Service, StateLog, PingLog

logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def notification(service, is_up, dashboard_url, downtime_seconds=None):
    title = "Service recovered" if is_up else "Service is down"
    message = f"<b>{title}</b>\n\nService: {escape(service.name or service.url)}\nURL: {escape(service.url)}"
    if downtime_seconds is not None:
        message += f"\nObserved downtime: {max(0, round(downtime_seconds))}s"
    if dashboard_url.strip():
        parts = urlsplit(dashboard_url.strip())
        dashboard = urlunsplit(parts._replace(fragment=f"service-{service.id}"))
        message += f'\n\n<a href="{escape(dashboard, quote=True)}">View downtime history</a>'
    return message


class TelegramNotifier:
    def __init__(self, settings):
        self.settings = settings
        self.enabled = bool(settings.bot_token and settings.chat_id)
        self.queue = asyncio.Queue(maxsize=1000)

    def enqueue(self, message):
        if not self.enabled:
            return
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("Telegram queue full; notification dropped")

    async def run(self):
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.settings.bot_token}/sendMessage"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            while True:
                message = await self.queue.get()
                try:
                    # Retry in place to preserve DOWN/recovery order.
                    for attempt in range(5):
                        delay = min(2 ** attempt, 30)
                        try:
                            async with session.post(url, json={
                                "chat_id": self.settings.chat_id, "text": message,
                                "parse_mode": "HTML", "link_preview_options": {"is_disabled": True},
                            }) as response:
                                if response.status == 200:
                                    break
                                if response.status == 429:
                                    data = await response.json()
                                    parameters = data.get("parameters") if isinstance(data, dict) else None
                                    retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
                                    if type(retry_after) is int and retry_after > 0:
                                        delay = retry_after
                                elif response.status < 500:
                                    logger.warning("Telegram rejected notification (HTTP %s)", response.status)
                                    break
                        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                            logger.warning("Telegram delivery failed; retrying")
                        await asyncio.sleep(delay)
                    else:
                        logger.warning("Telegram retry limit reached; notification dropped")
                    await asyncio.sleep(3)
                finally:
                    self.queue.task_done()


async def ping_url(session, url):
    started = time.monotonic()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            return response.status < 400 or response.status in (401, 403, 405), (time.monotonic() - started) * 1000
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False, (time.monotonic() - started) * 1000


async def check_service(session_maker, aio_session, service_id, notifier, settings, last_samples):
    async with session_maker() as session:
        service = await session.get(Service, service_id)
        if service is None:
            return
        url = service.url
    # Network timeouts must not occupy the database connection pool.
    is_up, ping_ms = await ping_url(aio_session, url)
    now = utcnow()
    tick = time.monotonic()
    async with session_maker() as session:
        service = await session.get(Service, service_id)
        if service is None or service.url != url:
            return
        sample_due = tick - last_samples.get(service_id, float('-inf')) >= settings.ping_sample_interval
        if sample_due:
            session.add(PingLog(service_id=service.id, timestamp=now, ping_ms=ping_ms))
        last_log = await session.scalar(select(StateLog).where(
            StateLog.service_id == service.id, StateLog.end_time.is_(None),
        ).order_by(StateLog.start_time.desc()).limit(1))
        downtime = None
        if last_log is None:
            session.add(StateLog(service_id=service.id, state=is_up, start_time=now))
        elif last_log.state != is_up:
            if is_up:
                downtime = (now - last_log.start_time).total_seconds()
            last_log.end_time = now
            session.add(StateLog(service_id=service.id, state=is_up, start_time=now))

        changed = service.notified_down != (not is_up)
        service.notified_down = not is_up
        message = notification(service, is_up, settings.dashboard_url, downtime) if changed else None
        await session.commit()
        if sample_due:
            last_samples[service_id] = tick
        if message:
            notifier.enqueue(message)


async def cleanup_history(session_maker, retention_days, now=None, batch_size=1000, max_batches=100):
    cutoff = (now or utcnow()) - timedelta(days=retention_days)
    deleted = 0
    # Keep open intervals and intervals crossing the retention boundary.
    for model, column in ((PingLog, PingLog.timestamp), (StateLog, StateLog.end_time)):
        for _ in range(max_batches):
            async with session_maker() as session:
                ids = list((await session.scalars(select(model.id).where(column < cutoff).order_by(column).limit(batch_size))).all())
                if not ids:
                    break
                await session.execute(delete(model).where(model.id.in_(ids), column < cutoff))
                await session.commit()
                deleted += len(ids)
            await asyncio.sleep(0.05)
    return deleted


async def retention_loop(session_maker, settings):
    while True:
        try:
            deleted = await cleanup_history(session_maker, settings.retention_days)
            logger.info("History cleanup removed %s rows", deleted)
        except Exception:
            logger.error("History cleanup failed; will retry in one hour")
        await asyncio.sleep(3600)


async def monitor_loop(session_maker, settings):
    async with session_maker() as session:
        for url in settings.urls:
            if await session.scalar(select(Service).where(Service.url == url)) is None:
                session.add(Service(url=url, name=urlsplit(url).netloc or url))
        await session.commit()

    notifier = TelegramNotifier(settings)
    workers = [asyncio.create_task(notifier.run()), asyncio.create_task(retention_loop(session_maker, settings))]
    last_samples = {}
    try:
        async with aiohttp.ClientSession() as aio_session:
            while True:
                started = time.monotonic()
                try:
                    async with session_maker() as session:
                        ids = list((await session.scalars(select(Service.id))).all())
                    results = await asyncio.gather(*[
                        check_service(session_maker, aio_session, sid, notifier, settings, last_samples) for sid in ids
                    ], return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception):
                            logger.error("Service check failed (%s)", type(result).__name__)
                except Exception as exc:
                    logger.error("Monitor cycle failed (%s)", type(exc).__name__)
                await asyncio.sleep(max(0.1, settings.check_interval - (time.monotonic() - started)))
    finally:
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
