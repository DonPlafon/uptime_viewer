import aiohttp
import asyncio
import time
import os
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import Service, StateLog, PingLog

PING_INTERVAL = 60 # Check every 60 seconds

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

async def check_service(db_session: AsyncSession, aio_session: aiohttp.ClientSession, service: Service):
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
    
    while True:
        try:
            async with session_maker() as session:
                stmt = select(Service)
                result = await session.execute(stmt)
                services = result.scalars().all()

                async with aiohttp.ClientSession() as aio_session:
                    tasks = [check_service(session, aio_session, srv) for srv in services]
                    await asyncio.gather(*tasks)
            
        except Exception as e:
            print(f"Monitor error: {e}")
        
        await asyncio.sleep(PING_INTERVAL)
