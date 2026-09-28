"""Container probe; uses only the Python standard library."""
import sys
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def main():
    try:
        with build_opener(ProxyHandler({})).open('http://127.0.0.1:8000/health', timeout=4) as response:
            return 0 if response.status == 200 else 1
    except (URLError, OSError):
        return 1


if __name__ == '__main__':
    sys.exit(main())
