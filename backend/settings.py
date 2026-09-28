import os
from dataclasses import dataclass
from urllib.parse import urlsplit


def validate_http_url(value, field):
    # urlsplit silently removes some control characters; reject them first.
    try:
        if not value or len(value) > 2048 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError
    except ValueError:
        raise ValueError(f"{field} must be an HTTP(S) URL without credentials, fragments or whitespace (max 2048 characters)") from None
    return value


@dataclass(frozen=True)
class Settings:
    check_interval: int = 10
    ping_sample_interval: int = 60
    retention_days: int = 90
    dashboard_url: str = ""
    bot_token: str = ""
    chat_id: str = ""
    urls: tuple[str, ...] = ()

    @classmethod
    def from_env(cls):
        def integer(name, default, minimum, maximum):
            value = int(os.getenv(name) or default)
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")
            return value

        dashboard = os.getenv("DASHBOARD_URL") or cls.dashboard_url
        dashboard = dashboard.strip(" ") if dashboard.strip() else ""
        if dashboard:
            validate_http_url(dashboard, "DASHBOARD_URL")
        urls = tuple(dict.fromkeys(validate_http_url(value.strip(" "), "URLS")
                                  for value in os.getenv("URLS", "").split(",") if value.strip()))
        return cls(
            check_interval=integer("CHECK_INTERVAL_SECONDS", 10, 5, 300),
            ping_sample_interval=integer("PING_SAMPLE_SECONDS", 60, 60, 3600),
            retention_days=integer("HISTORY_RETENTION_DAYS", 90, 30, 365),
            dashboard_url=dashboard,
            bot_token=os.getenv("TG_BOT_TOKEN", "").strip(),
            chat_id=os.getenv("TG_CHAT_ID", "").strip(),
            urls=urls,
        )
