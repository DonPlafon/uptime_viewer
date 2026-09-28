# UI Copy Review - Summary And Footer Removal

This change removes the following copy without introducing replacement strings.
The final text for every entry is absent: its containing element was removed.
Dynamic placeholders below are preserved from the previous source.

## Summary Above Service Cards

Source: removed `.overview` in `frontend/index.html` and its update logic in
`frontend/js/main.js`.

| Previous exact text | Final text |
| --- | --- |
| `Checking services` | Removed |
| `No services configured` | Removed |
| `${down} of ${services.length} services unavailable` | Removed |
| `${unknown} of ${services.length} services awaiting data` | Removed |
| `All ${services.length} services operational` | Removed |
| `Downtime color scale` (accessible name) | Removed |
| `Downtime` | Removed |
| `0%` | Removed |
| `5%` | Removed |
| `25%+` | Removed |

## Footer Below Service Cards

Source: removed `footer` in `frontend/index.html` and `#cadence` update in
`frontend/js/main.js`.

| Previous exact text | Final text |
| --- | --- |
| `Uptime Viewer` | Removed |
| `Checks every ${data[0].status.check_interval_seconds}s` | Removed |

The browser title, top repository link, refresh timestamp, per-service statuses,
empty-service message and algorithmic timeline colors are unchanged.
