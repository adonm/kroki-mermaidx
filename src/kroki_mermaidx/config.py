"""Configuration for the mermaidx companion service."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import urlparse

SERVICE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]{1,31}$")
SUPPORTED_FORMATS = ("svg", "png", "pdf")

try:
    _PACKAGE_VERSION = version("kroki-mermaidx")
except PackageNotFoundError:  # pragma: no cover - running from a source tree without an install
    _PACKAGE_VERSION = "0.0.0"


class ConfigError(ValueError):
    """Raised when the service configuration is invalid."""


def _env(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    value = _env(env, name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got: {value!r}") from exc


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    value = _env(env, name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got: {value!r}") from exc


def parse_size(value: str) -> int:
    """Parse a byte size such as ``1024``, ``512k``, ``1mb`` or ``2 MiB``."""
    normalized = value.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+)([kmgt]?i?b?)", normalized)
    if not match:
        raise ConfigError(f"Invalid size: {value!r}")
    amount = int(match.group(1))
    unit = match.group(2)
    multiplier = {
        "": 1,
        "b": 1,
        "k": 1024,
        "kb": 1024,
        "kib": 1024,
        "m": 1024**2,
        "mb": 1024**2,
        "mib": 1024**2,
        "g": 1024**3,
        "gb": 1024**3,
        "gib": 1024**3,
        "t": 1024**4,
        "tb": 1024**4,
        "tib": 1024**4,
    }[unit]
    return amount * multiplier


def _parse_formats(value: str) -> tuple[str, ...]:
    formats = tuple(dict.fromkeys(part.strip().lower() for part in value.split(",") if part.strip()))
    if not formats:
        raise ConfigError("MERMAIDX_FORMATS must contain at least one format")
    unsupported = sorted(set(formats) - set(SUPPORTED_FORMATS))
    if unsupported:
        raise ConfigError(
            f"Unsupported format(s): {', '.join(unsupported)} (supported: {', '.join(SUPPORTED_FORMATS)})"
        )
    return formats


def _validate_url(url: str, name: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{name} must be an absolute http(s) URL, got: {url!r}")
    return url.rstrip("/")


@dataclass(frozen=True)
class Settings:
    name: str
    version: str
    formats: tuple[str, ...]
    bind_host: str
    bind_port: int
    companion_host: str
    companion_port: int
    kroki_url: str | None
    registration_token: str | None
    heartbeat_interval: float
    register_retry_initial: float
    register_retry_max: float
    max_text_size: int
    max_edges: int
    max_body_size: int
    convert_timeout: float
    max_concurrency: int
    mermaidx_bin: str
    log_level: str

    @property
    def registration_enabled(self) -> bool:
        return self.kroki_url is not None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        bind_port = _int(env, "MERMAIDX_BIND_PORT", 8006)
        if not 1 <= bind_port <= 65535:
            raise ConfigError("MERMAIDX_BIND_PORT must be between 1 and 65535")

        companion_port = _int(env, "KROKI_COMPANION_PORT", bind_port)
        if not 1 <= companion_port <= 65535:
            raise ConfigError("KROKI_COMPANION_PORT must be between 1 and 65535")

        name = _env(env, "MERMAIDX_NAME") or "mermaidx"
        if not SERVICE_NAME_PATTERN.fullmatch(name):
            raise ConfigError(
                "MERMAIDX_NAME must match ^[a-z][a-z0-9]{1,31}$ (lowercase letters and digits, 2 to 32 characters)"
            )

        kroki_url = _env(env, "KROKI_URL")
        if kroki_url is not None:
            kroki_url = _validate_url(kroki_url, "KROKI_URL")

        max_text_size = _int(env, "MERMAIDX_MAX_TEXT_SIZE", 50000)
        if max_text_size < 1:
            raise ConfigError("MERMAIDX_MAX_TEXT_SIZE must be greater than 0")

        max_edges = _int(env, "MERMAIDX_MAX_EDGES", 500)
        if max_edges < 1:
            raise ConfigError("MERMAIDX_MAX_EDGES must be greater than 0")

        max_concurrency = _int(env, "MERMAIDX_MAX_CONCURRENCY", 4)
        if max_concurrency < 1:
            raise ConfigError("MERMAIDX_MAX_CONCURRENCY must be greater than 0")

        convert_timeout = _float(env, "MERMAIDX_CONVERT_TIMEOUT", 10.0)
        if convert_timeout <= 0:
            raise ConfigError("MERMAIDX_CONVERT_TIMEOUT must be greater than 0")

        heartbeat_interval = _float(env, "MERMAIDX_HEARTBEAT_INTERVAL", 30.0)
        if heartbeat_interval <= 0:
            raise ConfigError("MERMAIDX_HEARTBEAT_INTERVAL must be greater than 0")

        retry_initial = _float(env, "MERMAIDX_REGISTER_RETRY_INITIAL", 1.0)
        retry_max = _float(env, "MERMAIDX_REGISTER_RETRY_MAX", 30.0)
        if retry_initial <= 0 or retry_max < retry_initial:
            raise ConfigError("Register retry delays must be positive and retry max must be >= retry initial")

        return cls(
            name=name,
            version=_env(env, "MERMAIDX_VERSION") or _PACKAGE_VERSION,
            formats=_parse_formats(_env(env, "MERMAIDX_FORMATS") or "svg,png,pdf"),
            bind_host=_env(env, "MERMAIDX_BIND_HOST") or "0.0.0.0",
            bind_port=bind_port,
            companion_host=_env(env, "KROKI_COMPANION_HOST") or "mermaidx",
            companion_port=companion_port,
            kroki_url=kroki_url,
            registration_token=_env(env, "KROKI_COMPANION_REGISTRATION_TOKEN"),
            heartbeat_interval=heartbeat_interval,
            register_retry_initial=retry_initial,
            register_retry_max=retry_max,
            max_text_size=max_text_size,
            max_edges=max_edges,
            max_body_size=parse_size(_env(env, "MERMAIDX_MAX_BODY_SIZE") or "1mb"),
            convert_timeout=convert_timeout,
            max_concurrency=max_concurrency,
            mermaidx_bin=_env(env, "MERMAIDX_BIN") or "mermaidx",
            log_level=(_env(env, "MERMAIDX_LOG_LEVEL") or "info").lower(),
        )
