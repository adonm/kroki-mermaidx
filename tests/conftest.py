from __future__ import annotations

import dataclasses

import pytest

from kroki_mermaidx.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env({})


@pytest.fixture
def make_settings():
    def factory(**overrides) -> Settings:
        return dataclasses.replace(Settings.from_env({}), **overrides)

    return factory
