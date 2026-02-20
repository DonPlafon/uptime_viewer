import os
import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey

Base = declarative_base()

class Service(Base):
    __tablename__ = 'services'
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(2048), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)

class StateLog(Base):
    __tablename__ = 'state_logs'
    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey('services.id', ondelete='CASCADE'), nullable=False, index=True)
    state = Column(Boolean, nullable=False) # True = UP, False = DOWN
    start_time = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    end_time = Column(DateTime, nullable=True)

class PingLog(Base):
    __tablename__ = 'ping_logs'
    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey('services.id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)
    ping_ms = Column(Float, nullable=False)

def get_engine():
    user = os.getenv("DB_USER", "uptime")
    password = os.getenv("DB_PASSWORD", "uptime")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    db_name = os.getenv("DB_NAME", "uptime")
    
    conn_str = f"mysql+aiomysql://{user}:{password}@{host}:{port}/{db_name}"
    return create_async_engine(conn_str, echo=False)

def get_sessionmaker(engine):
    return async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

async def init_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
