import os
import asyncio
from datetime import datetime, timedelta, timezone
from sanic import Sanic
from sanic.response import json, file
from sqlalchemy import select, text
from database import get_engine, get_sessionmaker, init_db, Service, StateLog, PingLog
from monitor import monitor_loop

app = Sanic("UptimeViewer")

# Serve frontend static files
app.static('/css', '../frontend/css', name='css')
app.static('/js', '../frontend/js', name='js')

@app.route("/")
async def index(request):
    return await file("../frontend/index.html")

@app.before_server_start
async def setup_db(app, loop):
    app.ctx.engine = get_engine()
    app.ctx.session_maker = get_sessionmaker(app.ctx.engine)
    
    # Wait for DB to be ready
    for i in range(15):
        try:
            await init_db(app.ctx.engine)
            print("Database initialized successfully.")
            break
        except Exception as e:
            print(f"Failed to connect to db, retrying... ({i+1}/15) {e}")
            await asyncio.sleep(2)
            
    app.add_task(monitor_loop(app.ctx.engine, app.ctx.session_maker))

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

@app.get("/api/status/<service_id:int>")
async def get_status(request, service_id: int):
    hours = int(request.args.get("hours", 24))
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    
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
            
        return json({"logs": log_data, "period_hours": hours})

@app.get("/api/ping/<service_id:int>")
async def get_pings(request, service_id: int):
    hours = int(request.args.get("hours", 24))
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)

    async with app.ctx.session_maker() as session:
        query = text("""
            SELECT 
                DATE_FORMAT(timestamp, '%Y-%m-%d %H:00:00') as hour_time, 
                AVG(ping_ms) as avg_ping 
            FROM ping_logs 
            WHERE service_id = :service_id AND timestamp >= :cutoff
            GROUP BY hour_time 
            ORDER BY hour_time ASC
        """)
        
        result = await session.execute(query, {"service_id": service_id, "cutoff": cutoff})
        rows = result.fetchall()
        
        data = [{"time": row[0].replace(" ", "T") + "Z", "ping_ms": float(row[1])} for row in rows]
        return json({"pings": data})

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    app.run(host="0.0.0.0", port=8000, access_log=False)
