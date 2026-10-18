from __future__ import annotations

import pytest

from kroki_mermaidx.config import ConfigError, Settings, parse_size


def test_defaults():
    settings = Settings.from_env({})
    assert settings.name == "mermaidx"
    assert settings.bind_host == "0.0.0.0"
    assert settings.bind_port == 8006
    assert settings.companion_host == "mermaidx"
    assert settings.companion_port == 8006
    assert settings.formats == ("svg", "png", "pdf")
    assert settings.kroki_url is None
    assert settings.registration_enabled is False
    assert settings.max_text_size == 50000
    assert settings.max_edges == 500
    assert settings.max_body_size == 1024 * 1024
    assert settings.convert_timeout == 10.0
    assert settings.max_concurrency == 4
    assert settings.heartbeat_interval == 30.0


def test_companion_port_defaults_to_bind_port():
    settings = Settings.from_env({"MERMAIDX_BIND_PORT": "9010"})
    assert settings.bind_port == 9010
    assert settings.companion_port == 9010


def test_kroki_url_is_normalized_and_enables_registration():
    settings = Settings.from_env({"KROKI_URL": "http://kroki:8000/"})
    assert settings.kroki_url == "http://kroki:8000"
    assert settings.registration_enabled is True


def test_invalid_kroki_url():
    with pytest.raises(ConfigError):
        Settings.from_env({"KROKI_URL": "kroki:8000"})


@pytest.mark.parametrize("name", ["a", "Mermaidx", "mermaid x", "-mermaidx", "a" * 33])
def test_invalid_name(name):
    with pytest.raises(ConfigError):
        Settings.from_env({"MERMAIDX_NAME": name})


def test_empty_name_falls_back_to_default():
    assert Settings.from_env({"MERMAIDX_NAME": "  "}).name == "mermaidx"


def test_valid_name():
    assert Settings.from_env({"MERMAIDX_NAME": "mx1"}).name == "mx1"


def test_formats_are_normalized_and_deduplicated():
    settings = Settings.from_env({"MERMAIDX_FORMATS": "PNG, svg,png"})
    assert settings.formats == ("png", "svg")


def test_unsupported_format_rejected():
    with pytest.raises(ConfigError):
        Settings.from_env({"MERMAIDX_FORMATS": "svg,gif"})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1024", 1024),
        ("512k", 512 * 1024),
        ("1kb", 1024),
        ("1mb", 1024**2),
        ("2 MiB", 2 * 1024**2),
        ("1gb", 1024**3),
    ],
)
def test_parse_size(value, expected):
    assert parse_size(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "12xb", "-1mb"])
def test_parse_invalid_size(value):
    with pytest.raises(ConfigError):
        parse_size(value)


@pytest.mark.parametrize(
    ("env", "name"),
    [
        ({"MERMAIDX_BIND_PORT": "0"}, "MERMAIDX_BIND_PORT"),
        ({"MERMAIDX_BIND_PORT": "70000"}, "MERMAIDX_BIND_PORT"),
        ({"KROKI_COMPANION_PORT": "0"}, "KROKI_COMPANION_PORT"),
        ({"MERMAIDX_MAX_TEXT_SIZE": "0"}, "MERMAIDX_MAX_TEXT_SIZE"),
        ({"MERMAIDX_MAX_EDGES": "0"}, "MERMAIDX_MAX_EDGES"),
        ({"MERMAIDX_MAX_CONCURRENCY": "0"}, "MERMAIDX_MAX_CONCURRENCY"),
        ({"MERMAIDX_CONVERT_TIMEOUT": "0"}, "MERMAIDX_CONVERT_TIMEOUT"),
        ({"MERMAIDX_HEARTBEAT_INTERVAL": "-1"}, "MERMAIDX_HEARTBEAT_INTERVAL"),
        ({"MERMAIDX_BIND_PORT": "not-a-port"}, "MERMAIDX_BIND_PORT"),
    ],
)
def test_invalid_numbers(env, name):
    with pytest.raises(ConfigError) as exc:
        Settings.from_env(env)
    assert name in str(exc.value)


def test_register_retry_validation():
    with pytest.raises(ConfigError):
        Settings.from_env({"MERMAIDX_REGISTER_RETRY_INITIAL": "10", "MERMAIDX_REGISTER_RETRY_MAX": "5"})
