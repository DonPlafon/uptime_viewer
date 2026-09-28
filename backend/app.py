import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone
from sanic import Sanic
from sanic.response import json, file
from sqlalchemy import select, text
from database import get_engine, get_sessionmaker, init_db, Service, StateLog
from monitor import monitor_loop
from settings import Settings, validate_http_url

app = Sanic("UptimeViewer")

# Serve frontend static files
FRONTEND = Path(__file__).resolve().parent.parent / 'frontend'
app.static('/css', str(FRONTEND / 'css'), name='css')
app.static('/js', str(FRONTEND / 'js'), name='js')

@app.route("/")
async def index(request):
    return await file(str(FRONTEND / 'index.html'))

@app.get("/health")
async def health(request):
    headers = {"Cache-Control": "no-store"}
    try:
        task = request.app.get_task("monitor", raise_exception=False)
        if task is None or task.done():
            return json({"status": "unavailable"}, status=503, headers=headers)
        async with asyncio.timeout(3):
            async with request.app.ctx.session_maker() as session:
                await session.execute(text("SELECT 1"))
    except Exception:
        return json({"status": "unavailable"}, status=503, headers=headers)
    return json({"status": "ok"}, headers=headers)

@app.before_server_start
async def setup_db(app, loop):
    app.ctx.settings = Settings.from_env()
    app.ctx.engine = get_engine()
    app.ctx.session_maker = get_sessionmaker(app.ctx.engine)
    
    # Wait for DB to be ready
    for i in range(15):
        try:
            await init_db(app.ctx.engine)
            print("Database initialized successfully.")
            break
        except Exception:
            print(f"Database initialization failed, retrying... ({i+1}/15)")
            if i == 14:
                raise
            await asyncio.sleep(2)
            
    async with app.ctx.session_maker() as session:
        services = (await session.scalars(select(Service))).all()
        for service in services:
            validate_http_url(service.url, f"Stored service {service.id} URL")
    app.add_task(monitor_loop(app.ctx.session_maker, app.ctx.settings), name="monitor")

@app.before_server_stop
async def stop_monitor(app, loop):
    await app.cancel_task("monitor", raise_exception=False)

@app.after_server_stop
async def close_db(app, loop):
    await app.ctx.engine.dispose()

@app.get("/api/services")
async def get_services(request):
    async with app.ctx.session_maker() as session:
        stmt = select(Service)
        result = await session.execute(stmt)
        services = result.scalars().all()
        return json([{"id": s.id, "name": s.name, "url": s.url} for s in services])

def period_hours(request):
    try:
        return max(1, min(int(request.args.get("hours", 24)), 720))
    except (TypeError, ValueError):
        return 24

@app.get("/api/status/<service_id:int>")
async def get_status(request, service_id: int):
    hours = period_hours(request)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=hours)
    
    async with app.ctx.session_maker() as session:
        stmt = select(StateLog).where(
            StateLog.service_id == service_id,
            (StateLog.end_time >= cutoff) | (StateLog.end_time.is_(None))
        ).order_by(StateLog.start_time.asc())
        
        result = await session.execute(stmt)
        logs = result.scalars().all()
        
        log_data = []
        for l in logs:
            log_data.append({
                "state": "UP" if l.state else "DOWN",
                "start_time": l.start_time.isoformat() + "Z",
                "end_time": l.end_time.isoformat() + "Z" if l.end_time else None
            })
            
        return json({"logs": log_data, "period_hours": hours, "now": now.isoformat() + "Z",
                     "cutoff": cutoff.isoformat() + "Z", "check_interval_seconds": app.ctx.settings.check_interval})

@app.get("/api/ping/<service_id:int>")
async def get_pings(request, service_id: int):
    hours = period_hours(request)
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)

    async with app.ctx.session_maker() as session:
        query = text("""
            SELECT 
                DATE_FORMAT(timestamp, '%Y-%m-%d %H:00:00') as hour_time, 
                AVG(ping_ms) as avg_ping,
                COUNT(*) as samples
            FROM ping_logs 
            WHERE service_id = :service_id AND timestamp >= :cutoff
            GROUP BY hour_time 
            ORDER BY hour_time ASC
        """)
        
        result = await session.execute(query, {"service_id": service_id, "cutoff": cutoff})
        rows = result.fetchall()
        
        data = [{"time": row[0].replace(" ", "T") + "Z", "ping_ms": float(row[1]), "samples": int(row[2])} for row in rows]
        return json({"pings": data})

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    app.run(host="0.0.0.0", port=8000, access_log=False, single_process=True)
