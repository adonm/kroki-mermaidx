from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import httpx
import pytest

from kroki_mermaidx.config import Settings
from kroki_mermaidx.registration import Registrar


@dataclass
class FakeGateway:
    """A minimal in-memory implementation of the Kroki /services API."""

    require_token: str | None = None
    reject_registration: int | None = None
    registrations: dict[str, dict] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if self.require_token is not None:
            authorization = request.headers.get("authorization")
            if authorization != f"Bearer {self.require_token}":
                return httpx.Response(401, json={"error": "Missing or invalid bearer token."})

        path = request.url.path
        if request.method == "POST" and path == "/services":
            payload = json.loads(request.content)
            if self.reject_registration is not None:
                return httpx.Response(self.reject_registration, json={"error": "rejected"})
            if payload["name"] in self.registrations:
                return httpx.Response(422, json={"error": "already registered"})
            self.registrations[payload["name"]] = payload
            return httpx.Response(201, json={"name": payload["name"]})
        if request.method == "PUT" and path.endswith("/heartbeat"):
            name = path.split("/")[-2]
            if name not in self.registrations:
                return httpx.Response(404, json={"error": "not registered"})
            return httpx.Response(200, json={"name": name})
        if request.method == "GET" and path.startswith("/services/"):
            name = path.split("/")[-1]
            if name in self.registrations:
                return httpx.Response(200, json=self.registrations[name])
            return httpx.Response(404, json={"error": "not registered"})
        if request.method == "DELETE" and path.startswith("/services/"):
            name = path.split("/")[-1]
            self.registrations.pop(name, None)
            return httpx.Response(204)
        return httpx.Response(500, json={"error": "unexpected"})


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def registration_settings(make_settings) -> Settings:
    return make_settings(
        kroki_url="http://kroki:8000",
        registration_token="s3cr3t",
        heartbeat_interval=0.05,
        register_retry_initial=0.01,
        register_retry_max=0.05,
    )


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition was not met in time")


async def _run_registrar(settings: Settings, gateway: FakeGateway):
    client = httpx.AsyncClient(transport=httpx.MockTransport(gateway.handle))
    registrar = Registrar(settings, client=client)
    await registrar.start()
    return client, registrar


async def test_registers_heartbeats_and_unregisters(registration_settings, gateway):
    client, registrar = await _run_registrar(registration_settings, gateway)
    try:
        await _wait_until(lambda: registrar.registered)
        payload = gateway.registrations["mermaidx"]
        assert payload["version"] == registration_settings.version
        assert payload["formats"] == ["svg", "png", "pdf"]
        assert payload["host"] == "mermaidx"
        assert payload["port"] == 8006

        await _wait_until(lambda: any(method == "PUT" for method, _ in gateway.calls))
    finally:
        await registrar.stop()
        await client.aclose()
    assert "mermaidx" not in gateway.registrations


async def test_registration_is_retried_until_the_gateway_is_up(registration_settings, gateway):
    unavailable = FakeGateway(reject_registration=503)
    client = httpx.AsyncClient(transport=httpx.MockTransport(unavailable.handle))
    registrar = Registrar(registration_settings, client=client)
    await registrar.start()
    try:
        await _wait_until(lambda: len(unavailable.calls) >= 2)
        assert registrar.registered is False
        assert registrar.state == "registering"
    finally:
        await registrar.stop()
        await client.aclose()


async def test_invalid_token_reports_an_error(registration_settings, gateway):
    gateway.require_token = "another-token"
    client, registrar = await _run_registrar(registration_settings, gateway)
    try:
        await _wait_until(lambda: registrar.last_error is not None)
        assert "KROKI_COMPANION_REGISTRATION_TOKEN" in registrar.last_error
        assert registrar.registered is False
    finally:
        await registrar.stop()
        await client.aclose()


async def test_ambiguous_registration_reports_an_error(registration_settings, gateway):
    gateway.registrations["mermaidx"] = {
        "name": "mermaidx",
        "version": "9.9.9",
        "formats": ["svg"],
        "host": "somewhere",
        "port": 1234,
    }
    client, registrar = await _run_registrar(registration_settings, gateway)
    try:
        await _wait_until(lambda: registrar.last_error is not None)
        assert "already registered" in registrar.last_error
        assert registrar.registered is False
    finally:
        await registrar.stop()
        await client.aclose()


async def test_adopts_its_own_registration_after_a_restart(registration_settings, gateway):
    gateway.registrations["mermaidx"] = {
        "name": "mermaidx",
        "version": registration_settings.version,
        "formats": ["svg", "png", "pdf"],
        "host": "mermaidx",
        "port": 8006,
    }
    client, registrar = await _run_registrar(registration_settings, gateway)
    try:
        await _wait_until(lambda: registrar.registered)
        await _wait_until(lambda: any(method == "PUT" for method, _ in gateway.calls))
    finally:
        await registrar.stop()
        await client.aclose()


async def test_re_registers_after_the_gateway_restarts(registration_settings, gateway):
    client, registrar = await _run_registrar(registration_settings, gateway)
    try:
        await _wait_until(lambda: registrar.registered)
        # Simulate a gateway restart: the registry is in memory only.
        gateway.registrations.clear()
        await _wait_until(lambda: registrar.registered and "mermaidx" in gateway.registrations)
        posts = [method for method, path in gateway.calls if method == "POST" and path == "/services"]
        assert len(posts) >= 2
    finally:
        await registrar.stop()
        await client.aclose()


async def test_disabled_registration_does_nothing(settings: Settings, gateway):
    client, registrar = await _run_registrar(settings, gateway)
    try:
        assert registrar.state == "disabled"
        assert gateway.calls == []
    finally:
        await registrar.stop()
        await client.aclose()
