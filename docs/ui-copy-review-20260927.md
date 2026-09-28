# UI Copy Review - 2026-09-27

This records the initial implementation. Later removals from the header summary
and footer are recorded in [the removal review](ui-copy-review-20260927-removals.md)
and supersede the corresponding entries below.
The dashboard link is now optional; see [the optional-link review](ui-copy-review-20260927-optional-dashboard.md).

Only copy introduced or changed in this task is listed. Dynamic expressions are
preserved in code notation; runtime values depend on the selected service,
history and browser locale. No real service data is included.

## Telegram Notifications

Source: `backend/monitor.py:22`, `notification()`.
The title is bold. `View downtime history` is a link to
`{DASHBOARD_URL}#service-{service.id}` only when `DASHBOARD_URL` is configured.
Escaping does not change visible text.

Previous down notification from `tg-notifications`:

```text
🔴 ВНИМАНИЕ: Сервис недоступен!

Имя: {service.name}
URL: {service.url}
```

Final down notification:

```text
Service is down

Service: {service.name or service.url}
URL: {service.url}

View downtime history
```

Previous recovery notification:

```text
🟢 ОТБОЙ: Сервис снова доступен!

Имя: {service.name}
URL: {service.url}
```

Final recovery notification with a known outage start:

```text
Service recovered

Service: {service.name or service.url}
URL: {service.url}
Observed downtime: {max(0, round(downtime_seconds))}s

View downtime history
```

Final recovery notification without a known outage start:

```text
Service recovered

Service: {service.name or service.url}
URL: {service.url}

View downtime history
```

No Russian notification variant remains.

## Dashboard Header And Footer

| Location and source | Previous wording | Exact final text |
| --- | --- | --- |
| Repository link, `frontend/index.html:14` | Icon tooltip: `Source Code` | `UPTIME VIEWER` |
| Period group accessible name, `frontend/index.html:18` | None | `History period` |
| Initial refresh state, `frontend/index.html:23` | None | `Waiting for data` |
| Initial overall state, `frontend/index.html:27` | None | `Checking services` |
| Legend accessible name, `frontend/index.html:28` | None | `Downtime color scale` |
| Legend label, `frontend/index.html:29` | None | `Downtime` |
| Legend marks, same line | None | `0%`, `5%`, `25%+` |
| Footer identity, `frontend/index.html:34` | None | `Uptime Viewer` |
| Empty overall state, `frontend/js/main.js:163` | None | `No services configured` |
| Down overall state, same line | None | `${down} of ${services.length} services unavailable` |
| Unknown overall state, same line | None | `${unknown} of ${services.length} services awaiting data` |
| Healthy overall state, same line | None | `All ${services.length} services operational` |
| Refresh timestamp, `frontend/js/main.js:165` | None | `Updated ${new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'})}` |
| Poll cadence, `frontend/js/main.js:166` | None | `Checks every ${data[0].status.check_interval_seconds}s` |

The existing title, period button labels and initial `Loading services...` text
are unchanged and omitted.

## Service Status And Metrics

| Location and source | Previous wording | Exact final text |
| --- | --- | --- |
| Visible service URL, `frontend/js/main.js:21` | URL in icon tooltip only | `{service.url}` |
| Service name fallback, `frontend/js/main.js:19` | `{service.name}` | `{service.name || service.url}` |
| Current state, `frontend/js/main.js:30` | Indicator only | `Operational`, `Unavailable`, `No data` |
| Uptime metric label, `frontend/index.html:43` | Combined value `${uptimePct.toFixed(2)}% Uptime` | `Uptime` |
| Uptime value, `frontend/js/main.js:31` | `${uptimePct.toFixed(2)}% Uptime` | `${stats.uptime.toFixed(2)}%` or `N/A` |
| Outage metric label, `frontend/index.html:44` | None | `Outages` |
| Outage count, `frontend/js/main.js:33` | None | `{stats.outages.length}` or `N/A` |
| Downtime metric label, `frontend/index.html:45` | Value with `Downtime` suffix | `Total downtime` |
| Longest metric label, `frontend/index.html:46` | None | `Longest outage` |
| Response metric label, `frontend/index.html:47` | None | `Avg. response` |
| Response value, `frontend/js/main.js:39` | None | `${Math.round(validPings.reduce((sum, p) => sum + p.ping_ms * (p.samples ?? 1), 0) / count)} ms` or `N/A` |

Duration values now use `duration()` in `frontend/js/metrics.mjs:1`, for total
downtime, longest outage, timeline details and outage rows. Before, the total
used `${dtMins}m Downtime`, `${(dtMins / 60).toFixed(1)}h Downtime`, or
`${(dtMins / 1440).toFixed(1)}d Downtime`. Final duration formats are:

```text
<1s
${seconds}s
${minutes}m ${seconds % 60}s
${hours}h ${minutes % 60}m
${Math.floor(hours / 24)}d ${hours % 24}h
```

Total and longest downtime display `N/A` when there is no recorded history.

## Timeline And Chart

| Location and source | Previous wording | Exact final text |
| --- | --- | --- |
| Timeline accessible name, `frontend/index.html:50` | None | `Availability history` |
| Right timeline label, `frontend/index.html:51` | `Today` | `Now` |
| Chart title, `frontend/index.html:54` | `Ping History` | `Response time` |
| Chart unit, same line | None | `ms` |
| Chart accessible name, same line | None | `Average response time history` |
| Chart dataset, `frontend/js/main.js:103` | `Avg Ping (ms)` | `Average response time (ms)` |
| Chart load failure, `frontend/js/main.js:96` | None | `Chart unavailable.` |
| Chart empty state, same line | None | `No response samples yet.` |

Timeline tooltip/accessible label and the text shown on hover, focus or tap:
`frontend/js/main.js:48`.

Previous:

```text
${segStart.toLocaleString()} - ${isDown ? 'DOWN' : 'UP'}
```

Final variants:

```text
${dateTime(bucket.start)} - ${dateTime(bucket.end)} | No data
${dateTime(bucket.start)} - ${dateTime(bucket.end)} | ${(bucket.fraction * 100).toFixed(2)}% downtime (${duration(bucket.down)})
${dateTime(bucket.start)} - ${dateTime(bucket.end)} | ${(bucket.fraction * 100).toFixed(2)}% downtime (${duration(bucket.down)}) | Partial data
```

`dateTime()` uses the browser locale with month, day, hour, minute and second.
Existing left timeline labels and chart tooltip millisecond values are unchanged.

## Outage History

| Location and source | Previous wording | Exact final text |
| --- | --- | --- |
| Disclosure, `frontend/index.html:55`, `frontend/js/main.js:57` | None | `Recent outages` followed by `{stats.outages.length}` |
| Empty list, `frontend/js/main.js:62` | None | `No outages in this period.` |
| No history, same line | None | `No history yet.` |
| Outage start, `frontend/js/main.js:69` | None | `${dateTime(log.start_time)}` |
| Outage duration, `frontend/js/main.js:72` | None | `${duration(log.end - log.start)}` |
| Duration tooltip, `frontend/js/main.js:73` | None | `Downtime within the selected period` |
| Completed incident, `frontend/js/main.js:76` | None | `Resolved` |
| Active incident, same line | None | `Ongoing` |
| List limit, `frontend/js/main.js:83` | None | `Showing the latest 10 of ${stats.outages.length} outages.` |

## Loading And Errors

| Location and source | Previous wording | Exact final text |
| --- | --- | --- |
| No configured services, `frontend/js/main.js:148` | Empty screen | `No services configured.` |
| Refresh error, `frontend/js/main.js:176` | `Failed to load services.` | `Refresh failed. Showing the last successful update.` |
| Initial fetch error, same line | `Failed to load services.` | `Failed to load services. Retrying shortly.` |

The previous additional `Loading data...` replacement was removed; successful
content stays visible while refreshing. Fixture names used only in screenshot
tools are not production interface copy.
