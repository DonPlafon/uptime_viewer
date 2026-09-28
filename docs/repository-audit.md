# Repository Audit

Scope: current application/configuration/docs/test tooling and tracked Git history.
No production database, credentials, hosting configuration or Git history was changed.

## Fixed Findings

| Finding | Correction |
| --- | --- |
| IDE files and Telegram inbox attachments appeared as untracked publishable files | `.gitignore` now excludes these, environment variants, venvs, caches and local database/key files |
| Entire workspace was eligible for Docker build context upload | `.dockerignore` uses an application-source allowlist; `.env`, Git history, attachments, test tools and local dependencies stay out |
| Compose published MySQL on a random host port | Removed its `ports`; backend still connects through service DNS `db` |
| MySQL and backend silently used `root`/`uptime` passwords | Passwords are required explicitly; examples leave them blank |
| Passwords with URL punctuation could corrupt the connection URL | `backend/database.py` uses `URL.create`, with connection pre-ping and recycling |
| `.env.example` started polling unrelated sites | `URLS` is blank by default |
| Invalid or credential-bearing target URLs could be stored and published | Validate configured and already stored URLs before serving the app; error messages never repeat URL values |
| Unused `DEV_MODE` and obsolete Compose `version` | Removed |
| Backend image installed unused native MySQL build tools and ran as root | Removed those packages and run as UID/GID 10001; bytecode writes disabled |
| Tests depended on a private local dependency directory | Tests use the active Python environment, with declared development requirements |
| Screenshot tooling required a personal skill script path | Standalone `python tools/preview.py` works; external renderer is optional |
| Node syntax checking depended on automatic module detection | Explicit module syntax check through stdin; tests need Node 18+ |
| Old direct dependencies had known advisory records | Updated Sanic, aiohttp, aiomysql, python-dotenv and cryptography; audited resolved packages after updates |

The first PyPI-backed `pip-audit` report contained 43 unique advisory IDs across
five direct packages (the raw response repeated some entries). This counts known
package advisories, not proven exploitable paths in this application. Dependency
upgrade compatibility is covered by unit tests plus a real Sanic HTTP smoke test.
The Python package installer is also pinned to an updated version for image builds
and development environments, rather than relying on an older bundled pip.

The prior hardcoded dashboard address was already removed: `DASHBOARD_URL` is
optional and defaults to empty. The remaining production HTTP endpoints have
specific purposes: Telegram's API, the pinned Chart.js CDN asset, and this
repository's source-code link. Test/preview destinations use reserved example
domains or loopback. No personal deployment destination is a runtime default.

Targeted patterns for common tokens/private keys found no matches in the reviewed
source or tracked history; `.env` and private local files were not printed or
included in reports. This was a targeted scan, not a guarantee about arbitrary
secrets or the deployed environment.

## Upgrade Notes

- Set explicit `MYSQL_ROOT_PASSWORD` and `MYSQL_PASSWORD` before using the updated
  Compose file. For an existing volume use its actual current account credentials.
  Environment changes do not rotate existing MySQL passwords.
- MySQL is now reachable only inside the Compose network. Existing host-side DB
  tools need an intentional local-only port override or another administrative path.
- Existing container names remain unchanged to preserve scripts/proxy references.
- Invalid legacy URLs now prevent startup. Error messages identify the service ID;
  correct those stored values and configuration through normal administration.
- Query strings and URL paths may still contain arbitrary data and are public in
  the dashboard. Do not configure secret-bearing URLs. LAN monitoring is supported;
  this is not an SSRF boundary for untrusted users to submit arbitrary targets.

## Open Schema Issue

`backend/database.py` declares `Service.url` as `VARCHAR(2048)` with a full unique
index. Under MySQL's `utf8mb4` charset this may require up to 8,192 key bytes,
exceeding the usual 3,072-byte InnoDB limit. This is a blocker for creating that
index on a standard fresh `utf8mb4` database; existing working databases may have
different schema/charset settings. The comparison follows the
[MySQL InnoDB limits](https://dev.mysql.com/doc/refman/8.0/en/innodb-limits.html).

No destructive or guessed schema workaround was applied during this hygiene
audit. A separate migration should preserve IDs, history, existing collation
behavior and full URL values, and verify uniqueness on a real MySQL instance.
Simply truncating URLs, making them ASCII-only or using a unique prefix index can
change identity or reject valid URLs, so those shortcuts are unsuitable.

## Verification Limits

Final checks passed: 26 Python tests and 7 Node tests, including the isolated real
Sanic HTTP startup check. The final PyPI-backed audit of 57 installed packages in
the clean Windows/Python 3.11 development environment reported no known
vulnerabilities. Syntax and whitespace checks passed; Git ignore rules were
verified against representative IDE, Telegram, environment and generated files.

Tests use Python 3.11, SQLite and synthetic HTTP responses. MySQL-specific DDL,
hourly SQL aggregation, image build/non-root runtime and existing-volume upgrade
still require a Docker/MySQL environment. Neither is installed on this machine.
Live Telegram delivery was not exercised. This audit does not declare a fresh
MySQL deployment ready while the schema issue above remains open.

## Additional Full Review

The follow-up review reproduced and fixed three more defects:

- HTTP polling held database connections while waiting for remote targets. The
  read transaction now ends before HTTP begins; a fresh transaction checks that
  the target still exists and is unchanged before recording the result.
- The container probe honored environment proxies and could report a proxy's
  response as application health. Its opener now explicitly disables proxies.
- Telegram delays above 300 seconds were shortened, causing premature retries.
  Positive integer `retry_after` values are now honored without truncation;
  malformed response structures use the normal retry backoff without killing
  the delivery worker. The queue remains in-memory and delivery is best-effort.

Regression tests cover connection release and mid-flight target changes, proxy
bypass, a 900-second retry hint, and malformed Telegram response structures.
No UI text, production data, or deployed configuration changed in this follow-up.
