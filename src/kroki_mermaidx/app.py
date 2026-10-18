"""Starlette application exposing the mermaidx companion API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .config import Settings
from .errors import BadRequest, BodyTooLarge, ServiceError
from .registration import Registrar
from .renderer import Renderer

logger = logging.getLogger(__name__)

CONTENT_TYPES = {"svg": "image/svg+xml", "png": "image/png", "pdf": "application/pdf"}


def create_app(
    settings: Settings | None = None,
    *,
    renderer: Renderer | None = None,
    registrar: Registrar | None = None,
) -> Starlette:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: Starlette):
        mermaidx_version = None
        if renderer is None:
            app.state.renderer = Renderer(settings)
            mermaidx_version = await app.state.renderer.check()
        else:
            app.state.renderer = renderer
        app.state.mermaidx_version = mermaidx_version

        active_registrar = registrar
        if active_registrar is None and settings.registration_enabled:
            active_registrar = Registrar(settings)
        app.state.registrar = active_registrar
        if active_registrar is not None:
            await active_registrar.start()
        try:
            yield
        finally:
            if active_registrar is not None:
                await active_registrar.stop()

    routes = [
        Route("/", _info, methods=["GET"]),
        Route("/health", _health, methods=["GET"]),
        Route("/ready", _ready, methods=["GET"]),
        Route(f"/{settings.name}/{{output_format}}", _convert, methods=["POST"]),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.settings = settings
    app.state.renderer = None
    app.state.registrar = None
    app.state.mermaidx_version = None
    return app


async def _convert(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    renderer: Renderer = request.app.state.renderer
    output_format = request.path_params["output_format"].lower()

    if output_format not in settings.formats:
        formats = ", ".join(settings.formats)
        return _error_response(
            BadRequest(f"Unsupported output format '{output_format}'. Available formats are {formats}.")
        )

    try:
        raw = await _read_body(request, settings.max_body_size)
    except BodyTooLarge as error:
        return _error_response(error)

    if not raw.strip():
        return _error_response(BadRequest("Body must not be empty."))
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _error_response(BadRequest("Request body must be valid UTF-8."))

    options = _query_options(request)

    try:
        output = await renderer.render(source, output_format, options)
    except ServiceError as error:
        return _error_response(error)
    except Exception:  # pragma: no cover - defensive: never leak a 500 traceback
        logger.exception("Unexpected error while converting a diagram")
        return _error_response(ServiceError("An error occurred while converting the diagram."))

    return Response(
        output,
        media_type=CONTENT_TYPES.get(output_format, "application/octet-stream"),
        headers={"X-Mermaidx-Version": settings.version},
    )


async def _read_body(request: Request, limit: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                raise BodyTooLarge(f"Request body is too large (maximum is {limit} bytes)")
        except ValueError:
            pass
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise BodyTooLarge(f"Request body is too large (maximum is {limit} bytes)")
    return bytes(body)


def _query_options(request: Request) -> dict[str, Any]:
    # Mirror Kroki: the last value wins for a repeated query parameter.
    options: dict[str, Any] = {}
    for key, value in request.query_params.multi_items():
        options[key.lower()] = value
    return options


def _error_response(error: ServiceError) -> JSONResponse:
    return JSONResponse(error.to_dict(), status_code=error.status_code)


async def _health(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    registrar: Registrar | None = request.app.state.registrar
    return JSONResponse(
        {
            "status": "ok",
            "service": settings.name,
            "version": settings.version,
            "mermaidx": request.app.state.mermaidx_version or "unknown",
            "formats": list(settings.formats),
            "registration": {
                "state": registrar.state if registrar is not None else "disabled",
                "last_error": registrar.last_error if registrar is not None else None,
            },
        }
    )


async def _ready(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    registrar: Registrar | None = request.app.state.registrar
    if settings.registration_enabled and (registrar is None or not registrar.registered):
        return JSONResponse(
            {
                "status": "not-ready",
                "reason": "companion is not registered with the Kroki gateway",
                "last_error": registrar.last_error if registrar is not None else None,
            },
            status_code=503,
        )
    return JSONResponse({"status": "ready"})


async def _info(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    registrar: Registrar | None = request.app.state.registrar
    return JSONResponse(
        {
            "name": settings.name,
            "version": settings.version,
            "mermaidx": request.app.state.mermaidx_version or "unknown",
            "formats": list(settings.formats),
            "endpoints": {
                "convert": f"POST /{settings.name}/{{{','.join(settings.formats)}}}",
                "health": "GET /health",
                "ready": "GET /ready",
            },
            "kroki": {
                "url": settings.kroki_url,
                "registration": registrar.state if registrar is not None else "disabled",
            },
        }
    )
