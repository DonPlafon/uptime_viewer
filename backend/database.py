import os
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, inspect, text
from sqlalchemy.engine import URL

Base = declarative_base()

class Service(Base):
    __tablename__ = 'services'
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(2048), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    notified_down = Column(Boolean, nullable=False, default=False)

class StateLog(Base):
    __tablename__ = 'state_logs'
    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey('services.id', ondelete='CASCADE'), nullable=False, index=True)
    state = Column(Boolean, nullable=False) # True = UP, False = DOWN
    start_time = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    end_time = Column(DateTime, nullable=True, index=True)

class PingLog(Base):
    __tablename__ = 'ping_logs'
    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey('services.id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)
    ping_ms = Column(Float, nullable=False)

def get_engine():
    user = os.getenv("DB_USER", "uptime")
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise ValueError("DB_PASSWORD must be configured")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    db_name = os.getenv("DB_NAME", "uptime")
    
    connection_url = URL.create("mysql+aiomysql", username=user, password=password,
                                host=host, port=int(port), database=db_name)
    return create_async_engine(connection_url, echo=False, pool_pre_ping=True, pool_recycle=1800)

def get_sessionmaker(engine):
    return async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

async def init_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.run_sync(lambda sync: {c['name'] for c in inspect(sync).get_columns('services')})
        if 'notified_down' not in columns:
            await conn.execute(text("ALTER TABLE services ADD COLUMN notified_down BOOLEAN NOT NULL DEFAULT 0"))
        indexes = await conn.run_sync(lambda sync: inspect(sync).get_indexes('state_logs'))
        if not any(index['column_names'] == ['end_time'] for index in indexes):
            await conn.execute(text("CREATE INDEX ix_state_logs_end_time ON state_logs (end_time)"))
