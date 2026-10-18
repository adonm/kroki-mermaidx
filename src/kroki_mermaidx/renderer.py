"""Render Mermaid diagrams with mermaidx, one isolated process per request."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .errors import (
    ConvertTimeoutError,
    DiagramSyntaxError,
    MaxTextSizeError,
    RenderError,
    ServiceError,
    ServiceUnavailable,
)
from .mermaid_config import RenderOptions, build_render_options

logger = logging.getLogger(__name__)

# mermaidx wraps every Mermaid failure in a RuntimeError with this prefix.
# Using rfind keeps the last (and most specific) occurrence in the traceback.
_RENDER_ERROR_MARKER = "Mermaid rendering failed: "
_MAX_ERROR_MESSAGE_LENGTH = 4000
_MAX_ERROR_OUTPUT_LENGTH = 64 * 1024


@dataclass
class _CommandResult:
    stdout: bytes
    stderr: str
    returncode: int


class Renderer:
    """Runs the pinned mermaidx CLI in a subprocess.

    A process per request buys two things a warm in-process engine cannot:
    a hard timeout (a runaway QuickJS render is killed instead of blocking the
    service forever) and crash isolation. mermaidx itself is pinned at the
    packaging level (see pyproject.toml).
    """

    def __init__(
        self,
        settings: Settings,
        *,
        command: Sequence[str] | None = None,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self.settings = settings
        self._command = list(command) if command is not None else [settings.mermaidx_bin]
        self._semaphore = semaphore or asyncio.Semaphore(settings.max_concurrency)

    async def check(self) -> str | None:
        """Return the mermaidx version, or None if the executable is unusable."""
        try:
            result = await self._run(["--version"], b"", timeout=min(self.settings.convert_timeout, 10.0))
        except ServiceError as exc:
            logger.warning("Unable to run mermaidx: %s", exc)
            return None
        if result.returncode != 0:
            logger.warning("mermaidx --version failed: %s", result.stderr.strip())
            return None
        return result.stdout.decode("utf-8", errors="replace").strip() or None

    async def render(self, source: str, output_format: str, options: Mapping[str, Any]) -> bytes:
        if len(source) > self.settings.max_text_size:
            raise MaxTextSizeError(
                f"Diagram source is too large: {len(source)} characters (maximum is {self.settings.max_text_size})"
            )
        render_options = build_render_options(options, self.settings)
        async with self._semaphore:
            return await self._render(source, output_format, render_options)

    async def _render(self, source: str, output_format: str, options: RenderOptions) -> bytes:
        workdir = await asyncio.to_thread(tempfile.mkdtemp, prefix="kroki-mermaidx-")
        try:
            config_path = os.path.join(workdir, "config.json")
            await asyncio.to_thread(_write_json, config_path, options.config)

            if output_format == "svg":
                args = ["-i", "-", "--quiet", "--config", config_path]
                result = await self._run(args, source, self.settings.convert_timeout)
                return _fix_svg(result.stdout.decode("utf-8"))

            output_path = os.path.join(workdir, f"diagram.{output_format}")
            args = [
                "-i",
                "-",
                "--quiet",
                "-o",
                output_path,
                "--config",
                config_path,
                *_raster_args(options, output_format),
            ]
            await self._run(args, source, self.settings.convert_timeout)
            return await asyncio.to_thread(_read_file, output_path)
        finally:
            await asyncio.to_thread(shutil.rmtree, workdir, True)

    async def _run(self, args: list[str], source: bytes | str, timeout: float) -> _CommandResult:
        command = [*self._command, *args]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise ServiceUnavailable(f"mermaidx executable not found: {command[0]}") from exc

        payload = source.encode("utf-8") if isinstance(source, str) else source
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(input=payload), timeout=timeout)
        except TimeoutError as exc:
            await _kill(process)
            raise ConvertTimeoutError(f"Request timeout: convert took more than {int(timeout * 1000)}ms") from exc
        except asyncio.CancelledError:
            await _kill(process)
            raise

        stderr_text = stderr.decode("utf-8", errors="replace")[:_MAX_ERROR_OUTPUT_LENGTH]
        result = _CommandResult(stdout=stdout, stderr=stderr_text, returncode=process.returncode or 0)
        if result.returncode != 0:
            raise _error_from_stderr(result.stderr, result.returncode)
        return result


def _write_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


def _read_file(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _raster_args(options: RenderOptions, output_format: str) -> list[str]:
    args: list[str] = []
    if options.width is not None:
        args += ["--width", str(options.width)]
    if options.height is not None:
        args += ["--height", str(options.height)]
    if options.scale is not None:
        args += ["--scale", str(options.scale)]
    if options.background is not None:
        args += ["--background", options.background]
    if output_format == "pdf":
        if options.pdf_format is not None:
            args += ["--pdf-format", options.pdf_format]
        if options.pdf_landscape:
            args += ["--landscape"]
        if options.pdf_margin is not None:
            args += ["--margin", options.pdf_margin]
    return args


async def _kill(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        with suppress(ProcessLookupError):
            process.kill()
    with suppress(ProcessLookupError):  # pragma: no cover - defensive
        await process.wait()


def _fix_svg(svg: str) -> bytes:
    """Work around Mermaid emitting non-XML <br>/<img> tags (yuzutech/kroki#1632)."""
    if not svg.strip():
        raise RenderError("mermaidx produced empty SVG output")
    fixed = svg.replace("<br>", "<br/>")
    fixed = re.sub(r"<img([^>]*)>", lambda match: f"<img {match.group(1)} />", fixed)
    return fixed.encode("utf-8")


def _error_from_stderr(stderr: str, returncode: int) -> Exception:
    message = stderr.strip()
    marker_index = message.rfind(_RENDER_ERROR_MARKER)
    if marker_index != -1:
        detail = message[marker_index + len(_RENDER_ERROR_MARKER) :].strip()
        return DiagramSyntaxError(detail[:_MAX_ERROR_MESSAGE_LENGTH] or "Invalid Mermaid diagram")

    # mermaidx exits non-zero with a traceback on stderr. Keep the final
    # exception line (it usually names the actual problem) instead of the
    # whole traceback, which leaks container paths.
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    detail = lines[-1] if lines else f"mermaidx exited with code {returncode}"
    return RenderError(detail[:_MAX_ERROR_MESSAGE_LENGTH])
