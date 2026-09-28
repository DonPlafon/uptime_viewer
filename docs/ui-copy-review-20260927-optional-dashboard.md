# UI Copy Review - Optional Dashboard Link

Location: Telegram down and recovery notifications.
Source: `backend/monitor.py`, `notification()`.

Previously every notification ended with a blank line and `View downtime history`,
linked to the configured URL or a hardcoded fallback. The URL now defaults to empty.
When it is unset, empty or whitespace-only, that line and its preceding blank line
are absent. With an explicit URL, the notification wording and link label remain
unchanged. The monitored service's `URL:` line remains present in all variants.

## Final Down Notification Without A Dashboard URL

```text
Service is down

Service: {service.name or service.url}
URL: {service.url}
```

## Final Recovery Notification Without A Dashboard URL

When the outage start is known:

```text
Service recovered

Service: {service.name or service.url}
URL: {service.url}
Observed downtime: {max(0, round(downtime_seconds))}s
```

When the outage start is unknown:

```text
Service recovered

Service: {service.name or service.url}
URL: {service.url}
```

Titles remain bold in Telegram. No new notification wording was introduced.
