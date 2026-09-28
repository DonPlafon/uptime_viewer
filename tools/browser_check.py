"""Browser interaction and layout checks against the synthetic preview server."""
import asyncio
import json
from pathlib import Path
import sys

from playwright.async_api import async_playwright


async def main():
    url, output = sys.argv[1:]
    output = Path(output)
    errors = []
    results = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel='chrome', headless=True)
        try:
            context = await browser.new_context(device_scale_factor=2, locale='en-US', timezone_id='UTC')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            for name, width, height in [('desktop', 1440, 1100), ('tablet', 820, 1180), ('mobile', 390, 1200), ('small-mobile', 320, 1000)]:
                await page.set_viewport_size({'width': width, 'height': height})
                await page.goto(url, wait_until='networkidle')
                await page.wait_for_selector('.service-card')
                assert await page.locator('.service-card').count() == 3
                assert await page.locator('.segment').count() == 180
                assert await page.locator('#service-1 .downtime-total').inner_text() == '30s'
                assert await page.locator('#service-2 .outage-count').inner_text() == '4'
                assert await page.locator('#service-2 .current-status').inner_text() == 'Unavailable'
                overflow = await page.evaluate('''() => [...document.querySelectorAll('body *')].filter(e => {
                    const r = e.getBoundingClientRect();
                    return r.width && (r.right > innerWidth + 1 || r.left < -1);
                }).map(e => e.className || e.tagName)''')
                assert not overflow, (name, overflow)
                assert await page.locator('.chart-empty:visible').count() == 0, 'Chart asset failed to load'
                pixels = await page.evaluate('''() => [...document.querySelectorAll('canvas')].map(c => {
                    const bytes = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                    let count = 0; for(let i = 3; i < bytes.length; i += 4) if(bytes[i]) count++;
                    return count;
                })''')
                assert all(count > 100 for count in pixels), pixels
                await page.locator('#service-1 summary').click()
                assert await page.locator('#service-1 .outage-row').count() == 2
                await page.locator('#service-1 .segment').nth(10).focus()
                assert await page.locator('#service-1 .segment-detail').inner_text()
                await page.locator('#service-1 .segment').nth(10).evaluate('(el) => el.blur()')
                await page.locator('#service-1 summary').click()
                await page.mouse.move(0, 0)
                if name in ('desktop', 'tablet', 'mobile'):
                    await page.screenshot(path=str(output / f'uptime-{name}-2x.png'), full_page=True)
                results.append({'viewport': name, 'overflow': overflow, 'chart_pixels': pixels})

            await page.locator('[data-period="168"]').click()
            await page.wait_for_function("document.querySelector('.start-label').textContent === '7 days ago'")
            await page.locator('[data-period="720"]').click()
            await page.locator('[data-period="24"]').click()
            await page.wait_for_function("document.querySelector('.start-label').textContent === '24 hours ago'")
            await page.wait_for_timeout(300)
            assert await page.locator('[data-period="24"]').get_attribute('aria-pressed') == 'true'

            async def fail(route):
                await route.fulfill(status=503, body='unavailable')
            await page.route('**/api/services', fail)
            await page.locator('[data-period="168"]').click()
            await page.wait_for_selector('#refresh-error:visible')
            assert await page.locator('.service-card').count() == 3
            assert 'last successful' in await page.locator('#refresh-error').inner_text()
            await page.unroute('**/api/services', fail)

            async def empty(route):
                await route.fulfill(json=[])
            await page.route('**/api/services', empty)
            await page.reload(wait_until='networkidle')
            assert await page.locator('.loading-state').inner_text() == 'No services configured.'
            await page.unroute('**/api/services', empty)

            async def no_history(route):
                from datetime import datetime, timedelta, timezone
                now = datetime.now(timezone.utc)
                await route.fulfill(json={'logs': [], 'now': now.isoformat(), 'cutoff': (now - timedelta(days=1)).isoformat(), 'check_interval_seconds': 10})
            await page.route('**/api/status/*', no_history)
            await page.reload(wait_until='networkidle')
            assert await page.locator('#service-1 .uptime-percentage').inner_text() == 'N/A'
            assert await page.locator('#service-1 .current-status').inner_text() == 'No data'
            await page.unroute('**/api/status/*', no_history)
            await page.goto(url + '/#service-2', wait_until='networkidle')
            await page.wait_for_timeout(100)
            assert await page.locator('#service-2').evaluate('(el) => Math.abs(el.getBoundingClientRect().top - 20) < 2')
            assert not errors, errors
            (output / 'browser-checks.json').write_text(json.dumps({'results': results, 'page_errors': errors, 'interaction_checks': 'passed'}, indent=2), encoding='utf-8')
            print('Browser checks passed: 4 viewports, charts, periods, empty/error states, service links.')
            await context.close()
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(asyncio.wait_for(main(), timeout=110))
