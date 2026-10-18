from __future__ import annotations

from importlib.metadata import version as _version

from starlette.testclient import TestClient

from kroki_mermaidx.app import create_app
from kroki_mermaidx.errors import ConvertTimeoutError, DiagramSyntaxError


def _mermaidx_version() -> str:
    return _version("mermaidx")


class FakeRenderer:
    def __init__(self, output: bytes = b"<svg>ok</svg>", error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.calls: list[tuple[str, str, dict]] = []

    async def render(self, source: str, output_format: str, options) -> bytes:
        self.calls.append((source, output_format, dict(options)))
        if self.error is not None:
            raise self.error
        return self.output


class StubRegistrar:
    def __init__(self, registered: bool = True) -> None:
        self._registered = registered
        self.started = False
        self.stopped = False
        self.last_error: str | None = None

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    @property
    def registered(self) -> bool:
        return self._registered

    @property
    def state(self) -> str:
        return "registered" if self._registered else "registering"


def _client(settings, renderer=None, registrar=None):
    app = create_app(settings, renderer=renderer or FakeRenderer(), registrar=registrar or StubRegistrar())
    return TestClient(app)


def test_health(make_settings):
    with _client(make_settings()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "mermaidx"
    assert body["formats"] == ["svg", "png", "pdf"]
    assert body["registration"]["state"] == "registered"


def test_info(make_settings):
    with _client(make_settings()) as client:
        body = client.get("/").json()
    assert body["name"] == "mermaidx"
    assert "svg" in body["endpoints"]["convert"]


def test_render_svg(make_settings):
    renderer = FakeRenderer()
    with _client(make_settings(), renderer=renderer) as client:
        response = client.post("/mermaidx/svg", content="flowchart LR; A-->B")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["x-mermaidx-version"]
    assert response.content == b"<svg>ok</svg>"
    assert renderer.calls[0][0] == "flowchart LR; A-->B"
    assert renderer.calls[0][1] == "svg"


def test_render_png(make_settings):
    with _client(make_settings(), renderer=FakeRenderer()) as client:
        response = client.post("/mermaidx/png", content="flowchart LR; A-->B")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")


def test_render_pdf(make_settings):
    with _client(make_settings(), renderer=FakeRenderer()) as client:
        response = client.post("/mermaidx/pdf", content="flowchart LR; A-->B")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")


def test_query_options_are_lowercased_and_last_wins(make_settings):
    renderer = FakeRenderer()
    with _client(make_settings(), renderer=renderer) as client:
        client.post("/mermaidx/svg?Theme=dark&theme=forest&flowchart_curve=linear", content="flowchart LR; A-->B")
    assert renderer.calls[0][2] == {"theme": "forest", "flowchart_curve": "linear"}


def test_empty_body(make_settings):
    with _client(make_settings()) as client:
        response = client.post("/mermaidx/svg", content=b"   ")
    assert response.status_code == 400
    assert response.json()["error"]["name"] == "BadRequest"


def test_invalid_utf8_body(make_settings):
    with _client(make_settings()) as client:
        response = client.post("/mermaidx/svg", content=b"\xff\xfe")
    assert response.status_code == 400
    assert "UTF-8" in response.json()["error"]["message"]


def test_body_too_large(make_settings):
    with _client(make_settings(max_body_size=16)) as client:
        response = client.post("/mermaidx/svg", content=b"x" * 17)
    assert response.status_code == 400
    assert response.json()["error"]["name"] == "BodyTooLarge"


def test_unsupported_format(make_settings):
    with _client(make_settings()) as client:
        response = client.post("/mermaidx/gif", content="flowchart LR; A-->B")
    assert response.status_code == 400
    assert "Unsupported output format" in response.json()["error"]["message"]


def test_syntax_error_mapping(make_settings):
    renderer = FakeRenderer(error=DiagramSyntaxError("Parse error on line 1"))
    with _client(make_settings(), renderer=renderer) as client:
        response = client.post("/mermaidx/svg", content="nope")
    assert response.status_code == 400
    body = response.json()["error"]
    assert body["name"] == "SyntaxError"
    assert body["message"] == "Parse error on line 1"


def test_timeout_mapping(make_settings):
    renderer = FakeRenderer(error=ConvertTimeoutError("Request timeout"))
    with _client(make_settings(), renderer=renderer) as client:
        response = client.post("/mermaidx/svg", content="flowchart LR; A-->B")
    assert response.status_code == 408
    assert response.json()["error"]["name"] == "TimeoutError"


def test_unexpected_error_mapping(make_settings):
    renderer = FakeRenderer(error=RuntimeError("boom"))
    with _client(make_settings(), renderer=renderer) as client:
        response = client.post("/mermaidx/svg", content="flowchart LR; A-->B")
    assert response.status_code == 500
    assert response.json()["error"]["name"] == "Error"
    assert "boom" not in response.json()["error"]["message"]


def test_ready_reflects_registration(make_settings):
    settings = make_settings(kroki_url="http://kroki:8000")
    with _client(settings, registrar=StubRegistrar(registered=False)) as client:
        assert client.get("/ready").status_code == 503
    with _client(settings, registrar=StubRegistrar(registered=True)) as client:
        assert client.get("/ready").status_code == 200


def test_lifespan_starts_and_stops_registrar(make_settings):
    registrar = StubRegistrar()
    with _client(make_settings(kroki_url="http://kroki:8000"), registrar=registrar) as client:
        assert registrar.started is True
        client.get("/health")
    assert registrar.stopped is True


def test_health_reports_probed_mermaidx_version(make_settings):
    app = create_app(make_settings(), registrar=StubRegistrar())
    with TestClient(app) as client:
        assert client.get("/health").json()["mermaidx"] == _mermaidx_version()
