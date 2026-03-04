import aiohttp
import asyncio
import time
import os
import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import Service, StateLog, PingLog

PING_INTERVAL = 60 # Check every 60 seconds

class TelegramNotifier:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.bot_token = os.getenv("TG_BOT_TOKEN")
        self.chat_id = os.getenv("TG_CHAT_ID")
        self.worker_task = None

    def start(self):
        if self.bot_token and self.chat_id:
            self.worker_task = asyncio.create_task(self._worker())

    async def stop(self):
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

    async def send_message(self, message: str):
        if not self.bot_token or not self.chat_id:
            return
        await self.queue.put(message)

    async def _worker(self):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        async with aiohttp.ClientSession() as session:
            while True:
                message = await self.queue.get()
                payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
                
                try:
                    async with session.post(url, json=payload, timeout=5) as resp:
                        if resp.status == 429:
                            # Rate limit hit, wait and retry
                            response_data = await resp.json()
                            retry_after = response_data.get("parameters", {}).get("retry_after", 5)
                            print(f"Telegram rate limit hit. Waiting {retry_after} seconds.")
                            await asyncio.sleep(retry_after)
                            await self.queue.put(message) # Put back in queue
                        elif resp.status >= 400:
                            print(f"Telegram API error: {resp.status} - {await resp.text()}")
                        else:
                            # Success, respect basic rate limit (e.g., max 20 msgs/min to a group -> ~3 sec delay)
                            await asyncio.sleep(1)
                except Exception as e:
                    print(f"Failed to send TG message, requeuing: {e}")
                    await asyncio.sleep(2)  # Wait before requeueing on network error
                    await self.queue.put(message)
                finally:
                    self.queue.task_done()

tg_notifier = TelegramNotifier()


async def ping_url(session: aiohttp.ClientSession, url: str):
    start_t = time.monotonic()
    try:
        async with session.get(url, timeout=10) as response:
            ping_ms = (time.monotonic() - start_t) * 1000
            # Some sites return 401/403 which means they're up but auth required
            is_up = response.status < 400 or response.status in (401, 403, 405)
            return is_up, ping_ms
    except Exception as e:
        ping_ms = (time.monotonic() - start_t) * 1000
        return False, ping_ms

async def check_service(session_maker, aio_session: aiohttp.ClientSession, service_id: int):
    # Create isolated DB session for this task
    async with session_maker() as db_session:
        # Re-fetch service to ensure we have attached instance in this session
        stmt = select(Service).where(Service.id == service_id)
        result = await db_session.execute(stmt)
        service = result.scalar_one_or_none()
        
        if not service:
            return

        is_up, ping_ms = await ping_url(aio_session, service.url)
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Record ping
        ping_log = PingLog(service_id=service.id, timestamp=now, ping_ms=ping_ms)
        db_session.add(ping_log)

        # Check last state
        stmt = select(StateLog).where(
            StateLog.service_id == service.id,
            StateLog.end_time.is_(None)
        ).order_by(StateLog.start_time.desc()).limit(1)
        
        result = await db_session.execute(stmt)
        last_log = result.scalar_one_or_none()

        if last_log is None:
            new_log = StateLog(service_id=service.id, state=is_up, start_time=now)
            db_session.add(new_log)
        elif last_log.state != is_up:
            last_log.end_time = now
            new_log = StateLog(service_id=service.id, state=is_up, start_time=now)
            db_session.add(new_log)
            
        if not is_up and not service.notified_down:
            await tg_notifier.send_message(f"🔴 <b>ВНИМАНИЕ: Сервис недоступен!</b>\n\nИмя: {service.name}\nURL: {service.url}")
            service.notified_down = True
            db_session.add(service)
        elif is_up and service.notified_down:
            await tg_notifier.send_message(f"🟢 <b>ОТБОЙ: Сервис снова доступен!</b>\n\nИмя: {service.name}\nURL: {service.url}")
            service.notified_down = False
            db_session.add(service)
        
        await db_session.commit()

async def monitor_loop(db_engine, session_maker):
    urls_env = os.getenv("URLS", "")
    urls = [u.strip() for u in urls_env.split(",") if u.strip()]

    async with session_maker() as session:
        for url in urls:
            stmt = select(Service).where(Service.url == url)
            result = await session.execute(stmt)
            srv = result.scalar_one_or_none()
            if not srv:
                hostname = url.split("//")[-1].split("/")[0]
                srv = Service(url=url, name=hostname)
                session.add(srv)
        await session.commit()
    
    tg_notifier.start()
    
    try:
        while True:
            try:
                # Fetch all service IDs first to avoid keeping session open during gather
                async with session_maker() as session:
                    stmt = select(Service.id)
                    result = await session.execute(stmt)
                    service_ids = result.scalars().all()

                async with aiohttp.ClientSession() as aio_session:
                    tasks = [check_service(session_maker, aio_session, sid) for sid in service_ids]
                    await asyncio.gather(*tasks)
                
            except Exception as e:
                print(f"Monitor error: {e}")
            
            await asyncio.sleep(PING_INTERVAL)
    finally:
        await tg_notifier.stop()
