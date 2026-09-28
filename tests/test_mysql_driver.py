"""Exercise the installed MySQL dialect without a running database server."""
import unittest
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiomysql.connection import Connection
from sqlalchemy.dialects.mysql.aiomysql import AsyncAdapt_aiomysql_connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.util.concurrency import greenlet_spawn


class MySQLDriverTests(unittest.IsolatedAsyncioTestCase):
    async def test_pre_ping_uses_async_adapter_without_reconnecting(self):
        engine = create_async_engine('mysql+aiomysql://', pool_pre_ping=True)
        raw = SimpleNamespace(ping=AsyncMock())
        connection = AsyncAdapt_aiomysql_connection(engine.dialect.dbapi, raw)
        try:
            for _ in range(2):
                self.assertTrue(await greenlet_spawn(engine.dialect.do_ping, connection))
            self.assertEqual(raw.ping.await_count, 2)
            for call in raw.ping.await_args_list:
                arguments = inspect.signature(Connection.ping).bind(raw, *call.args, **call.kwargs)
                arguments.apply_defaults()
                self.assertIs(arguments.arguments['reconnect'], False)
        finally:
            await engine.dispose()
