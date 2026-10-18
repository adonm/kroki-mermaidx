from __future__ import annotations

import pytest

from kroki_mermaidx.errors import BadRequest
from kroki_mermaidx.mermaid_config import (
    build_render_options,
    convert_property_to_key,
    default_config,
    typed_value,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("theme", "theme"),
        ("flowchart_curve", "flowchart.curve"),
        ("themeVariables_primaryColor", "themeVariables.primaryColor"),
        ("sequence_actor-margin", "sequence.actorMargin"),
        ("gantt_bar-gap", "gantt.barGap"),
    ],
)
def test_convert_property_to_key(value, expected):
    assert convert_property_to_key(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("false", False),
        ("42", 42),
        ("1.5", 1.5),
        ("-3", -3),
        ("[a,b]", ["a", "b"]),
        ("[1,2]", [1, 2]),
        ("dark", "dark"),
        ("", ""),
    ],
)
def test_typed_value(value, expected):
    assert typed_value(value) == expected


def test_default_config_has_kroki_defaults(make_settings):
    settings = make_settings(max_text_size=1234, max_edges=99)
    config = default_config(settings)
    assert config["maxTextSize"] == 1234
    assert config["maxEdges"] == 99
    assert config["securityLevel"] == "strict"
    assert config["htmlLabels"] is False
    for key in ("class", "er", "flowchart", "gantt", "git", "journey", "sequence", "state"):
        assert config[key]["useMaxWidth"] is False


def test_build_render_options(make_settings):
    settings = make_settings()
    options = build_render_options(
        {
            "theme": "dark",
            "flowchart_curve": "linear",
            "themeVariables_primaryColor": "#ff0000",
            "width": "640",
            "height": "480.5",
            "scale": "2",
            "background": "#ffffff",
            "pdf_format": "A4",
            "pdf_landscape": "true",
            "pdf_margin": "1cm",
        },
        settings,
    )
    assert options.config["theme"] == "dark"
    assert options.config["flowchart"]["curve"] == "linear"
    assert options.config["themeVariables"]["primaryColor"] == "#ff0000"
    # defaults survive the merge with request options
    assert options.config["flowchart"]["useMaxWidth"] is False
    assert options.width == 640
    assert options.height == 480.5
    assert options.scale == 2
    assert options.background == "#ffffff"
    assert options.pdf_format == "A4"
    assert options.pdf_landscape is True
    assert options.pdf_margin == "1cm"


def test_lowercased_keys_keep_lowercase_paths(make_settings):
    # Kroki lowercases every query parameter before forwarding it, so a client
    # going through the gateway cannot target camelCase Mermaid keys. This is
    # the same behaviour as the built-in Mermaid companion.
    options = build_render_options({"themevariables_primarycolor": "#ff0000"}, make_settings())
    assert options.config["themevariables"]["primarycolor"] == "#ff0000"


@pytest.mark.parametrize(
    "key",
    ["maxTextSize", "max_text_size", "maxEdges", "securityLevel", "secure", "startOnLoad", "safeMode"],
)
def test_denied_options_are_ignored(make_settings, key):
    options = build_render_options({key: "1"}, make_settings())
    assert key.lower() not in options.config
    assert options.config["maxTextSize"] == 50000
    assert options.config["maxEdges"] == 500
    assert options.config["securityLevel"] == "strict"


def test_unlikely_option_keys_are_ignored(make_settings):
    options = build_render_options({"flowchart lr a[hello]-->b": ""}, make_settings())
    assert options.config["maxTextSize"] == 50000
    assert all(" " not in key for key in options.config)


@pytest.mark.parametrize("key", ["width", "height", "scale"])
def test_invalid_numbers_are_rejected(make_settings, key):
    with pytest.raises(BadRequest):
        build_render_options({key: "wide"}, make_settings())
    with pytest.raises(BadRequest):
        build_render_options({key: "0"}, make_settings())


def test_invalid_pdf_boolean_is_rejected(make_settings):
    with pytest.raises(BadRequest):
        build_render_options({"pdf_landscape": "maybe"}, make_settings())


def test_empty_background_is_rejected(make_settings):
    with pytest.raises(BadRequest):
        build_render_options({"background": "  "}, make_settings())
