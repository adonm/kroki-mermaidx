"""A browserless Mermaid companion service for Kroki, powered by mermaidx."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kroki-mermaidx")
except PackageNotFoundError:  # pragma: no cover - source tree without an install
    __version__ = "0.0.0"

__all__ = ["__version__"]
