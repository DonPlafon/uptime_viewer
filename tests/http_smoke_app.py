"""Isolated Sanic fixture: SQLite, synthetic checks, no Telegram or live targets."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from sqlalchemy.ext.asyncio import create_async_engine
import app as web
import monitor
from settings import Settings


async def synthetic_ping(session, url):
    return True, 12.0


if __name__ == '__main__':
    web.get_engine = lambda: create_async_engine('sqlite+aiosqlite:///:memory:')
    web.Settings.from_env = classmethod(lambda cls: Settings(urls=('https://example.com/',)))
    monitor.ping_url = synthetic_ping
    web.app.run(host='127.0.0.1', port=int(sys.argv[1]), access_log=False,
                single_process=True, auto_reload=False)
