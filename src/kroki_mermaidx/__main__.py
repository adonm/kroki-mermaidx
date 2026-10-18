"""Command line entry point: ``kroki-mermaidx``."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys

import uvicorn

from . import __version__
from .app import create_app
from .config import ConfigError, Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="kroki-mermaidx",
        description="A browserless Mermaid companion service for Kroki, powered by mermaidx.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--host", help="Bind address (default: MERMAIDX_BIND_HOST or 0.0.0.0)")
    parser.add_argument("--port", type=int, help="Bind port (default: MERMAIDX_BIND_PORT or 8006)")
    parser.add_argument("--log-level", help="Log level: critical, error, warning, info, debug (default: info)")
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        parser.error(str(exc))

    overrides = {}
    if args.host:
        overrides["bind_host"] = args.host
    if args.port:
        overrides["bind_port"] = args.port
    if args.log_level:
        overrides["log_level"] = args.log_level.lower()
    if overrides:
        settings = dataclasses.replace(settings, **overrides)

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("kroki_mermaidx")
    logger.info(
        "Starting %s v%s on %s:%s (formats: %s)",
        settings.name,
        settings.version,
        settings.bind_host,
        settings.bind_port,
        ",".join(settings.formats),
    )
    if settings.registration_enabled:
        logger.info(
            "Companion service discovery enabled: registering with %s as %s:%s",
            settings.kroki_url,
            settings.companion_host,
            settings.companion_port,
        )
        if not settings.registration_token:
            logger.warning(
                "KROKI_COMPANION_REGISTRATION_TOKEN is not set: "
                "anyone who can reach the gateway's /services API can register a companion"
            )

    try:
        uvicorn.run(
            create_app(settings), host=settings.bind_host, port=settings.bind_port, log_level=settings.log_level
        )
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":
    main()
