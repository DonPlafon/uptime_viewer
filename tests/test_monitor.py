import asyncio
import json
import os
from pathlib import Path
import sys
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from sqlalchemy import select, text, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from database import Base, Service, StateLog, PingLog, init_db, get_sessionmaker, get_engine
from monitor import TelegramNotifier, check_service, cleanup_history, notification
from settings import Settings, validate_http_url


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        await init_db(self.engine)
        self.sessions = get_sessionmaker(self.engine)
        async with self.sessions() as session:
            session.add(Service(id=1, url='https://example.com/?a=1&b=2', name='Example <API>'))
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_cleanup_boundaries_and_open_intervals(self):
        now = datetime(2026, 9, 27)
        cutoff = now - timedelta(days=31)
        async with self.sessions() as session:
            session.add_all([
                PingLog(service_id=1, timestamp=cutoff - timedelta(seconds=1), ping_ms=10),
                PingLog(service_id=1, timestamp=cutoff, ping_ms=20),
                PingLog(service_id=1, timestamp=now, ping_ms=30),
                StateLog(service_id=1, state=False, start_time=cutoff - timedelta(days=3), end_time=cutoff - timedelta(seconds=1)),
                StateLog(service_id=1, state=False, start_time=cutoff - timedelta(days=2), end_time=cutoff),
                StateLog(service_id=1, state=True, start_time=cutoff - timedelta(days=1), end_time=now),
                StateLog(service_id=1, state=False, start_time=cutoff - timedelta(days=5)),
            ])
            await session.commit()
        self.assertEqual(await cleanup_history(self.sessions, 31, now, batch_size=1), 2)
        async with self.sessions() as session:
            self.assertEqual(len((await session.scalars(select(PingLog))).all()), 2)
            self.assertEqual(len((await session.scalars(select(StateLog))).all()), 3)

    async def test_cleanup_is_bounded(self):
        async with self.sessions() as session:
            session.add_all([PingLog(service_id=1, timestamp=datetime(2000, 1, 1), ping_ms=10) for _ in range(5)])
            await session.commit()
        self.assertEqual(await cleanup_history(self.sessions, 31, batch_size=2, max_batches=1), 2)
        async with self.sessions() as session:
            self.assertEqual(len((await session.scalars(select(PingLog))).all()), 3)

    async def test_short_outage_sampling_and_notifications(self):
        settings = Settings(bot_token='test', chat_id='test')
        notifier = TelegramNotifier(settings)
        samples = {}
        now = datetime(2026, 9, 27)
        for tick, up in [(100, True), (110, False), (120, True), (160, True)]:
            with patch('monitor.ping_url', AsyncMock(return_value=(up, 123))), patch('monitor.utcnow', return_value=now + timedelta(seconds=tick)), patch('monitor.time', SimpleNamespace(monotonic=lambda: tick)):
                await check_service(self.sessions, None, 1, notifier, settings, samples)
        async with self.sessions() as session:
            logs = list((await session.scalars(select(StateLog).order_by(StateLog.start_time))).all())
            self.assertEqual([log.state for log in logs], [True, False, True])
            self.assertEqual((logs[1].end_time - logs[1].start_time).total_seconds(), 10)
            self.assertEqual(len((await session.scalars(select(PingLog))).all()), 2)
        self.assertEqual(notifier.queue.qsize(), 2)
        self.assertIn('Service is down', notifier.queue.get_nowait())
        self.assertIn('Observed downtime: 10s', notifier.queue.get_nowait())

    async def test_failed_commit_does_not_send_or_advance_sample(self):
        notifier = TelegramNotifier(Settings(bot_token='test', chat_id='test'))
        samples = {}
        with patch('monitor.ping_url', AsyncMock(return_value=(False, 10))), patch('sqlalchemy.ext.asyncio.AsyncSession.commit', AsyncMock(side_effect=RuntimeError('db failed'))):
            with self.assertRaises(RuntimeError):
                await check_service(self.sessions, None, 1, notifier, Settings(), samples)
        self.assertEqual(samples, {})
        self.assertTrue(notifier.queue.empty())

    async def test_http_probe_releases_database_and_ignores_changed_target(self):
        async def probe(*args):
            # No transaction may span the outbound HTTP request.
            self.assertFalse(self.engine.sync_engine.pool.connection.in_use)
            async with self.sessions() as session:
                service = await session.get(Service, 1)
                service.url = 'https://changed.example.com/'
                await session.commit()
            return False, 10

        notifier = TelegramNotifier(Settings(bot_token='test', chat_id='test'))
        samples = {}
        with patch('monitor.ping_url', side_effect=probe):
            await check_service(self.sessions, None, 1, notifier, Settings(), samples)
        self.assertEqual(samples, {})
        self.assertTrue(notifier.queue.empty())
        async with self.sessions() as session:
            self.assertEqual(list(await session.scalars(select(StateLog))), [])

    async def test_blank_telegram_and_queue_limit(self):
        for settings in [Settings(), Settings(bot_token='test'), Settings(chat_id='test')]:
            notifier = TelegramNotifier(settings)
            notifier.enqueue('ignored')
            await notifier.run()
            self.assertTrue(notifier.queue.empty())
        notifier = TelegramNotifier(Settings(bot_token='test', chat_id='test'))
        for _ in range(1001):
            notifier.enqueue('test')
        self.assertEqual(notifier.queue.qsize(), 1000)

    async def test_telegram_retries_in_fifo_order(self):
        sent = []
        statuses = iter([429, 500, 200, 200])

        class Response:
            def __init__(self, status):
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def json(self):
                return {'parameters': {'retry_after': 7}}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def post(self, url, json):
                sent.append(json['text'])
                return Response(next(statuses))

        notifier = TelegramNotifier(Settings(bot_token='test', chat_id='test'))
        notifier.enqueue('DOWN')
        notifier.enqueue('RECOVERED')
        with patch('monitor.aiohttp.ClientSession', return_value=Client()), patch('monitor.asyncio.sleep', new_callable=AsyncMock) as sleep:
            task = asyncio.create_task(notifier.run())
            try:
                await asyncio.wait_for(notifier.queue.join(), timeout=5)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(sent, ['DOWN', 'DOWN', 'DOWN', 'RECOVERED'])
            self.assertEqual([call.args[0] for call in sleep.await_args_list], [7, 2, 3, 3])

    async def test_telegram_long_and_malformed_retry_delays(self):
        from unittest.mock import MagicMock
        for payload, delay in [({'parameters': {'retry_after': 900}}, 900),
                               ({'parameters': None}, 1), ([], 1),
                               ({'parameters': {'retry_after': None}}, 1)]:
            with self.subTest(payload=payload):
                response = MagicMock()
                response.__aenter__.return_value = response
                response.json = AsyncMock(return_value=payload)
                response.status = 429
                success = MagicMock()
                success.__aenter__.return_value = success
                success.status = 200
                client = MagicMock()
                client.__aenter__.return_value = client
                client.post.side_effect = [response, success]
                notifier = TelegramNotifier(Settings(bot_token='test', chat_id='test'))
                notifier.enqueue('DOWN')
                with patch('monitor.aiohttp.ClientSession', return_value=client), patch('monitor.asyncio.sleep', new_callable=AsyncMock) as sleep:
                    task = asyncio.create_task(notifier.run())
                    try:
                        await asyncio.wait_for(notifier.queue.join(), 2)
                        self.assertFalse(task.done())
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    self.assertEqual([call.args[0] for call in sleep.await_args_list], [delay, 3])

    async def test_api_status_uses_utc_boundaries(self):
        import app as web
        web.app.ctx.session_maker = self.sessions
        web.app.ctx.settings = Settings()
        async with self.sessions() as session:
            session.add(StateLog(service_id=1, state=False, start_time=datetime.utcnow() - timedelta(seconds=5)))
            await session.commit()
        response = await web.get_status(SimpleNamespace(args={'hours': 'invalid'}), 1)
        data = json.loads(response.body)
        self.assertEqual(data['period_hours'], 24)
        self.assertEqual(data['check_interval_seconds'], 10)
        self.assertEqual(data['logs'][0]['state'], 'DOWN')
        self.assertTrue(data['now'].endswith('Z'))
        self.assertEqual(web.period_hours(SimpleNamespace(args={'hours': '99999'})), 720)

    async def test_failed_startup_never_starts_monitor(self):
        import app as web
        fake = SimpleNamespace(ctx=SimpleNamespace(), add_task=AsyncMock())
        with patch.dict(os.environ, {}, clear=True), patch('app.get_engine', return_value=self.engine), patch('app.init_db', AsyncMock(side_effect=RuntimeError('migration failed'))), patch('app.asyncio.sleep', new_callable=AsyncMock):
            with self.assertRaises(RuntimeError):
                await web.setup_db(fake, None)
        fake.add_task.assert_not_called()

    async def test_startup_rejects_legacy_url_credentials_without_exposing_them(self):
        import app as web
        async with self.sessions() as session:
            service = await session.get(Service, 1)
            service.url = 'https://private-user:private-password@example.com/'
            await session.commit()
        fake = SimpleNamespace(ctx=SimpleNamespace(), add_task=AsyncMock())
        with patch.dict(os.environ, {}, clear=True), patch('app.get_engine', return_value=self.engine):
            with self.assertRaises(ValueError) as error:
                await web.setup_db(fake, None)
        self.assertIn('Stored service 1 URL', str(error.exception))
        self.assertNotIn('private-', str(error.exception))
        fake.add_task.assert_not_called()

    def test_db_credentials_are_structured_and_required(self):
        secret = 'test@password/#:%'
        with patch.dict(os.environ, {'DB_PASSWORD': secret, 'DB_USER': 'test@user'}, clear=True), patch('database.create_async_engine') as create:
            get_engine()
            connection = create.call_args.args[0]
            self.assertEqual(connection.password, secret)
            self.assertEqual(connection.username, 'test@user')
            self.assertEqual(connection.host, 'localhost')
            self.assertTrue(create.call_args.kwargs['pool_pre_ping'])
        for env in ({}, {'DB_PASSWORD': ''}):
            with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(ValueError, 'DB_PASSWORD must be configured'):
                get_engine()

    def test_target_urls_are_validated_without_echoing_input(self):
        for url in ['file:///etc/passwd', 'https://user:secret@example.com', 'https://example.com:bad',
                    'https://example.com:70000', 'https://', 'https://example.com/#fragment',
                    'https://exam\nple.com', '\thttps://example.com', 'https://example.com\n']:
            with self.subTest(url=url), self.assertRaises(ValueError) as error:
                validate_http_url(url, 'URLS')
            self.assertNotIn('secret', str(error.exception))
            self.assertNotIn('example.com', str(error.exception))
        for field in ('URLS', 'DASHBOARD_URL'):
            with patch.dict(os.environ, {field: 'https://example.com\n'}, clear=True), self.assertRaises(ValueError):
                Settings.from_env()
        with patch.dict(os.environ, {'URLS': ' http://127.0.0.1:8080/ ,https://example.com/,https://example.com/'}, clear=True):
            self.assertEqual(Settings.from_env().urls, ('http://127.0.0.1:8080/', 'https://example.com/'))

    async def test_health_success(self):
        import app as web
        request = SimpleNamespace(app=SimpleNamespace(
            get_task=lambda *args, **kwargs: SimpleNamespace(done=lambda: False),
            ctx=SimpleNamespace(session_maker=self.sessions)))
        response = await web.health(request)
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body), {'status': 'ok'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    async def test_health_missing_finished_and_cancelled_monitor(self):
        import app as web
        finished = asyncio.get_running_loop().create_future()
        finished.set_result(None)
        cancelled = asyncio.get_running_loop().create_future()
        cancelled.cancel()
        for task in (None, finished, cancelled):
            request = SimpleNamespace(app=SimpleNamespace(get_task=lambda *args, **kwargs: task))
            response = await web.health(request)
            self.assertEqual(response.status, 503)
            self.assertEqual(json.loads(response.body), {'status': 'unavailable'})

    async def test_health_db_error_is_redacted(self):
        import app as web
        request = SimpleNamespace(app=SimpleNamespace(
            get_task=lambda *args, **kwargs: SimpleNamespace(done=lambda: False),
            ctx=SimpleNamespace(session_maker=self.sessions)))
        with patch('sqlalchemy.ext.asyncio.AsyncSession.execute', AsyncMock(side_effect=RuntimeError('private database details'))):
            response = await web.health(request)
        self.assertEqual(response.status, 503)
        self.assertEqual(json.loads(response.body), {'status': 'unavailable'})

    async def test_health_timeout_includes_session_acquisition(self):
        import app as web

        class WaitingSession:
            async def __aenter__(self):
                await asyncio.sleep(60)

            async def __aexit__(self, *args):
                pass

        request = SimpleNamespace(app=SimpleNamespace(
            get_task=lambda *args, **kwargs: SimpleNamespace(done=lambda: False),
            ctx=SimpleNamespace(session_maker=WaitingSession)))
        deadline = asyncio.timeout(0.01)
        with patch('app.asyncio.timeout', return_value=deadline):
            response = await web.health(request)
        self.assertEqual(response.status, 503)
        self.assertEqual(json.loads(response.body), {'status': 'unavailable'})

    def test_container_probe_exit_status(self):
        import healthcheck
        from unittest.mock import MagicMock
        from urllib.error import URLError
        for status, expected in [(200, 0), (503, 1)]:
            response = MagicMock()
            response.__enter__.return_value.status = status
            with patch('healthcheck.build_opener') as opener, patch('healthcheck.ProxyHandler') as proxy:
                opener.return_value.open.return_value = response
                self.assertEqual(healthcheck.main(), expected)
                proxy.assert_called_once_with({})
        with patch('healthcheck.build_opener') as opener:
            opener.return_value.open.side_effect = URLError('unavailable')
            self.assertEqual(healthcheck.main(), 1)

    async def test_shutdown_cancels_monitor_and_disposes_engine(self):
        import app as web
        fake = SimpleNamespace(cancel_task=AsyncMock(), ctx=SimpleNamespace(engine=SimpleNamespace(dispose=AsyncMock())))
        await web.stop_monitor(fake, None)
        fake.cancel_task.assert_awaited_once_with('monitor', raise_exception=False)
        await web.close_db(fake, None)
        fake.ctx.engine.dispose.assert_awaited_once()

    async def test_existing_schema_migration_and_repeat(self):
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as conn:
                await conn.execute(text('CREATE TABLE services (id INTEGER PRIMARY KEY, url VARCHAR(2048), name VARCHAR(255))'))
                await conn.execute(text("INSERT INTO services VALUES (1, 'https://example.com', 'Existing')"))
                await conn.execute(text('CREATE TABLE state_logs (id INTEGER PRIMARY KEY, service_id INTEGER, state BOOLEAN, start_time DATETIME, end_time DATETIME)'))
            await init_db(engine)
            await init_db(engine)
            async with engine.begin() as conn:
                self.assertEqual((await conn.execute(text('SELECT notified_down FROM services'))).scalar_one(), 0)
                indexes = await conn.run_sync(lambda sync: inspect(sync).get_indexes('state_logs'))
                self.assertTrue(any(index['column_names'] == ['end_time'] for index in indexes))
        finally:
            await engine.dispose()

    def test_notification_escapes_html_and_links_service(self):
        service = SimpleNamespace(id=7, name='<API>', url='https://example.com/?a=1&b=2')
        message = notification(service, False, 'https://status.example.com/#old')
        self.assertIn('&lt;API&gt;', message)
        self.assertIn('a=1&amp;b=2', message)
        self.assertIn('https://status.example.com/#service-7', message)
        self.assertIn('View downtime history', message)

    def test_settings_bounds_and_empty_values(self):
        self.assertEqual(Settings().retention_days, 90)
        for env, expected in [({}, 90), ({'HISTORY_RETENTION_DAYS': ''}, 90),
                              ({'HISTORY_RETENTION_DAYS': '31'}, 31)]:
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(Settings.from_env().retention_days, expected)
        with patch.dict(os.environ, {'TG_BOT_TOKEN': '', 'TG_CHAT_ID': '', 'CHECK_INTERVAL_SECONDS': '', 'HISTORY_RETENTION_DAYS': ''}, clear=True):
            self.assertEqual(Settings.from_env().check_interval, 10)
        with patch.dict(os.environ, {'HISTORY_RETENTION_DAYS': '29'}, clear=True):
            with self.assertRaises(ValueError):
                Settings.from_env()
        with patch.dict(os.environ, {'DASHBOARD_URL': 'javascript:alert(1)'}, clear=True):
            with self.assertRaises(ValueError):
                Settings.from_env()

    def test_optional_dashboard_defaults_and_notifications(self):
        service = SimpleNamespace(id=7, name='Example', url='https://example.com')
        self.assertEqual(Settings().dashboard_url, '')
        for env in ({}, {'DASHBOARD_URL': ''}, {'DASHBOARD_URL': '   '}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                settings = Settings.from_env()
                self.assertEqual(settings.dashboard_url, '')
                self.assertEqual(notification(service, False, settings.dashboard_url),
                                 '<b>Service is down</b>\n\nService: Example\nURL: https://example.com')
                self.assertEqual(notification(service, True, settings.dashboard_url, 10),
                                 '<b>Service recovered</b>\n\nService: Example\nURL: https://example.com\nObserved downtime: 10s')
        self.assertNotIn('<a ', notification(service, False, '   '))
        with patch.dict(os.environ, {'DASHBOARD_URL': ' https://status.example.com/ '}, clear=True):
            configured = Settings.from_env()
            for is_up in (False, True):
                self.assertIn('href="https://status.example.com/#service-7"', notification(service, is_up, configured.dashboard_url))


if __name__ == '__main__':
    unittest.main()
