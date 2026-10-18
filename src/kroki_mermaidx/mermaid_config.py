"""Translate Kroki diagram options (query parameters) into mermaidx options.

Kroki forwards every request query parameter to the companion as an option.
The Mermaid companion turns these into a Mermaid configuration object, using
snake_case keys for nested properties (e.g. ``flowchart_curve=linear`` becomes
``{"flowchart": {"curve": "linear"}}``). We do the same, plus a few raster
options that mermaidx supports natively (``width``, ``height``, ``scale``,
``background`` and the PDF-specific options).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .errors import BadRequest

# Options that must not be overridden per request: they protect the service
# from resource exhaustion (or, for safe mode, from trusting the client).
DENIED_OPTIONS = {
    "maxtextsize",
    "maxedges",
    "securitylevel",
    "secure",
    "startonload",
    "safemode",
}

RASTER_OPTIONS = {"width", "height", "scale", "background"}
PDF_OPTIONS = {"pdf_format", "pdf_landscape", "pdf_margin"}
RESERVED_OPTIONS = RASTER_OPTIONS | PDF_OPTIONS

# Kroki forwards every query parameter as an option. Some clients also post a
# form-encoded body (curl's default --data-binary content type), which Vert.x
# can surface as an extra option whose key is the whole diagram source; only
# keys that could plausibly be Mermaid config paths are kept.
_OPTION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")


@dataclass
class RenderOptions:
    """Options for a single mermaidx invocation."""

    config: dict[str, Any] = field(default_factory=dict)
    width: float | None = None
    height: float | None = None
    scale: float | None = None
    background: str | None = None
    pdf_format: str | None = None
    pdf_landscape: bool = False
    pdf_margin: str | None = None


def default_config(settings: Settings) -> dict[str, Any]:
    """The Kroki-equivalent Mermaid defaults, plus the service limits.

    The built-in Mermaid companion disables ``useMaxWidth`` on every diagram
    type so that SVGs have an intrinsic pixel size instead of ``width="100%"``.
    """

    return {
        "maxTextSize": settings.max_text_size,
        "maxEdges": settings.max_edges,
        "securityLevel": "strict",
        "htmlLabels": False,
        "class": {"useMaxWidth": False},
        "er": {"useMaxWidth": False},
        "flowchart": {"useMaxWidth": False, "htmlLabels": False},
        "gantt": {"useMaxWidth": False},
        "git": {"useMaxWidth": False},
        "journey": {"useMaxWidth": False},
        "sequence": {"useMaxWidth": False},
        "state": {"useMaxWidth": False},
    }


def convert_property_to_key(property_name: str) -> str:
    """Mirror the Mermaid companion's ``convertPropertyToCamelCase``.

    ``flowchart_curve`` becomes ``flowchart.curve`` and ``themeVariables_primaryColor``
    becomes ``themeVariables.primaryColor``.
    """
    segments = []
    for segment in property_name.split("_"):
        parts = segment.split("-")
        if len(parts) > 1:
            parts = [parts[0]] + [part[:1].upper() + part[1:] for part in parts[1:]]
        segments.append("".join(parts))
    return ".".join(segments)


def typed_value(value: Any) -> Any:
    """Turn a query parameter string into a boolean, number, list or string."""
    if not isinstance(value, str):
        return value
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        return [typed_value(item) for item in inner.split(",")] if inner else []
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _set_nested(target: dict[str, Any], key: str, value: Any) -> None:
    keys = key.split(".")
    current = target
    for part in keys[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    current[keys[-1]] = value


def _positive_float(name: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise BadRequest(f"Option {name} must be a number, got: {value!r}") from exc
    if parsed <= 0:
        raise BadRequest(f"Option {name} must be greater than 0, got: {value!r}")
    return parsed


def _boolean(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise BadRequest(f"Option {name} must be a boolean, got: {value!r}")


def build_render_options(options: Mapping[str, Any], settings: Settings) -> RenderOptions:
    """Build mermaidx render options from Kroki diagram options."""
    result = RenderOptions(config=default_config(settings))
    lowered_options = {str(key).lower(): value for key, value in options.items()}

    for raw_key, raw_value in options.items():
        key = str(raw_key)
        lowered = key.lower()
        if lowered in DENIED_OPTIONS or lowered in RESERVED_OPTIONS:
            continue
        if not _OPTION_KEY_PATTERN.fullmatch(lowered):
            continue
        value = typed_value(raw_value)
        _set_nested(result.config, convert_property_to_key(key), value)

    if "width" in lowered_options:
        result.width = _positive_float("width", str(lowered_options["width"]))
    if "height" in lowered_options:
        result.height = _positive_float("height", str(lowered_options["height"]))
    if "scale" in lowered_options:
        result.scale = _positive_float("scale", str(lowered_options["scale"]))
    if "background" in lowered_options:
        background = str(lowered_options["background"]).strip()
        if not background:
            raise BadRequest("Option background must not be empty")
        result.background = background
    if "pdf_format" in lowered_options:
        result.pdf_format = str(lowered_options["pdf_format"]).strip() or None
    if "pdf_landscape" in lowered_options:
        result.pdf_landscape = _boolean("pdf_landscape", str(lowered_options["pdf_landscape"]))
    if "pdf_margin" in lowered_options:
        result.pdf_margin = str(lowered_options["pdf_margin"]).strip() or None

    return result
