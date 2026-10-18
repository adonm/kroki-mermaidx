from __future__ import annotations

import asyncio
import struct
import sys
import time

import pytest

from kroki_mermaidx.config import Settings
from kroki_mermaidx.errors import ConvertTimeoutError, DiagramSyntaxError, MaxTextSizeError, ServiceUnavailable
from kroki_mermaidx.renderer import Renderer

SOURCE = "flowchart LR\n  A[Hello] --> B{World?}\n"


async def test_render_svg(settings: Settings):
    output = await Renderer(settings).render(SOURCE, "svg", {})
    assert output.startswith(b"<svg")
    assert b"</svg>" in output
    # Kroki's Mermaid companion disables useMaxWidth, so the SVG has an
    # intrinsic size instead of filling its container.
    assert b'width="100%"' not in output


async def test_render_svg_honours_theme(settings: Settings):
    output = await Renderer(settings).render(SOURCE, "svg", {"theme": "dark"})
    assert b"#1f2020" in output


async def test_render_png(settings: Settings):
    output = await Renderer(settings).render(SOURCE, "png", {"width": "320", "background": "#ffffff"})
    assert output.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", output[16:24])
    assert width == 320
    assert height > 0


async def test_render_pdf(settings: Settings):
    output = await Renderer(settings).render(SOURCE, "pdf", {"pdf_format": "A4"})
    assert output.startswith(b"%PDF")


async def test_syntax_error(settings: Settings):
    with pytest.raises(DiagramSyntaxError) as exc:
        await Renderer(settings).render("not a diagram", "svg", {})
    assert "UnknownDiagramError" in str(exc.value)
    assert "Traceback" not in str(exc.value)


async def test_max_text_size(make_settings):
    settings = make_settings(max_text_size=10)
    with pytest.raises(MaxTextSizeError) as exc:
        await Renderer(settings).render("flowchart LR; A-->B", "svg", {})
    assert "too large" in str(exc.value)


async def test_invalid_raster_option(settings: Settings):
    from kroki_mermaidx.errors import BadRequest

    with pytest.raises(BadRequest):
        await Renderer(settings).render(SOURCE, "png", {"width": "wide"})


async def test_missing_executable(settings: Settings):
    renderer = Renderer(settings, command=["definitely-not-a-mermaidx-binary"])
    with pytest.raises(ServiceUnavailable):
        await renderer.render(SOURCE, "svg", {})
    assert await renderer.check() is None


async def test_timeout_kills_the_process(make_settings):
    settings = make_settings(convert_timeout=0.5)
    renderer = Renderer(settings, command=[sys.executable, "-c", "import time; time.sleep(60)"])
    started = time.monotonic()
    with pytest.raises(ConvertTimeoutError):
        await renderer.render(SOURCE, "svg", {})
    assert time.monotonic() - started < 5


async def test_check_reports_mermaidx_version(settings: Settings):
    assert await Renderer(settings).check() == "0.9.5"


async def test_concurrency_limit(make_settings):
    settings = make_settings(max_concurrency=1)
    renderer = Renderer(settings, semaphore=asyncio.Semaphore(1))
    results = await asyncio.gather(
        renderer.render(SOURCE, "svg", {}),
        renderer.render(SOURCE, "svg", {"theme": "dark"}),
    )
    assert all(result.startswith(b"<svg") for result in results)
    assert len(results[1]) > 0
