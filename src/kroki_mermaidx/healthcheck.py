"""Container health check used by the Dockerfile HEALTHCHECK instruction."""

from __future__ import annotations

import os
import sys
import urllib.request


def main() -> None:
    port = os.environ.get("MERMAIDX_BIND_PORT", "8006")
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status != 200:
                print(f"{url} returned HTTP {response.status}", file=sys.stderr)
                sys.exit(1)
    except Exception as exc:
        print(f"{url} is not healthy: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
