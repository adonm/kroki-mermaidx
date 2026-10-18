"""Register the service with a Kroki gateway (companion service discovery)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import httpx

from .config import Settings

logger = logging.getLogger(__name__)


class Registrar:
    """Registers with the Kroki gateway and keeps the registration alive.

    The gateway keeps registrations in memory only, so the companion must
    register at startup, send a heartbeat before the heartbeat TTL expires,
    and register again if the gateway restarted (a heartbeat then returns 404).
    """

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=5.0)
        self._owns_client = client is None
        self._registered = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.last_error: str | None = None

    @property
    def registered(self) -> bool:
        return self._registered.is_set()

    @property
    def state(self) -> str:
        if not self.settings.registration_enabled:
            return "disabled"
        if self.registered:
            return "registered"
        return "registering"

    async def start(self) -> None:
        if not self.settings.registration_enabled:
            logger.info("KROKI_URL is not set: companion service discovery is disabled")
            return
        self._task = asyncio.create_task(self._run(), name="kroki-registration")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            with suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._task, timeout=5.0)
            if not self._task.done():
                self._task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._task
            self._task = None
        if self._registered.is_set():
            await self._unregister()
        if self._owns_client:
            await self._client.aclose()

    async def _run(self) -> None:
        delay = self.settings.register_retry_initial
        while not self._stop.is_set():
            try:
                if not self._registered.is_set():
                    if await self._register():
                        delay = self.settings.register_retry_initial
                        continue
                else:
                    if await _wait(self._stop, self.settings.heartbeat_interval):
                        return
                    await self._heartbeat()
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive: keep the loop alive
                logger.exception("Registration loop failed; retrying")

            if await _wait(self._stop, delay):
                return
            delay = min(delay * 2, self.settings.register_retry_max)

    async def _register(self) -> bool:
        payload = {
            "name": self.settings.name,
            "version": self.settings.version,
            "formats": list(self.settings.formats),
            "host": self.settings.companion_host,
            "port": self.settings.companion_port,
        }
        try:
            response = await self._client.post(self._url("/services"), json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            self.last_error = f"Unable to reach Kroki at {self.settings.kroki_url}: {exc}"
            logger.warning("%s", self.last_error)
            return False

        if response.status_code == 201:
            self._registered.set()
            self.last_error = None
            logger.info(
                "Registered companion '%s' v%s (%s) as %s:%s",
                self.settings.name,
                self.settings.version,
                ",".join(self.settings.formats),
                self.settings.companion_host,
                self.settings.companion_port,
            )
            return True

        if response.status_code == 422:
            # The name is already taken. After a restart of this same container
            # the gateway may still hold our previous registration until its
            # heartbeat TTL expires, so adopt it if it looks like us.
            existing = await self._get_registration()
            if existing is not None and existing.get("version") == self.settings.version:
                self._registered.set()
                self.last_error = None
                logger.info(
                    "Companion '%s' was already registered: adopting the existing registration", self.settings.name
                )
                return True
            self.last_error = (
                f"A service named '{self.settings.name}' is already registered with "
                f"{self.settings.kroki_url} (another instance or a stale registration)"
            )
            logger.warning("%s", self.last_error)
            return False

        if response.status_code in {401, 403}:
            self.last_error = (
                f"Kroki rejected the registration (HTTP {response.status_code}): "
                "check KROKI_COMPANION_REGISTRATION_TOKEN"
            )
            logger.error("%s", self.last_error)
            return False

        self.last_error = f"Unexpected registration response: HTTP {response.status_code} {response.text.strip()}"
        logger.warning("%s", self.last_error)
        return False

    async def _heartbeat(self) -> None:
        try:
            response = await self._client.put(
                self._url(f"/services/{self.settings.name}/heartbeat"), headers=self._headers()
            )
        except httpx.HTTPError as exc:
            logger.warning("Heartbeat failed: %s", exc)
            return

        if response.status_code == 200:
            self.last_error = None
            return
        if response.status_code == 404:
            logger.info("Registration lost (gateway restarted?): registering again")
            self._registered.clear()
            return
        if response.status_code in {401, 403}:
            logger.error("Heartbeat rejected (HTTP %s): check KROKI_COMPANION_REGISTRATION_TOKEN", response.status_code)
            return
        logger.warning("Unexpected heartbeat response: HTTP %s %s", response.status_code, response.text.strip())

    async def _get_registration(self) -> dict | None:
        try:
            response = await self._client.get(self._url(f"/services/{self.settings.name}"), headers=self._headers())
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def _unregister(self) -> None:
        try:
            await self._client.delete(self._url(f"/services/{self.settings.name}"), headers=self._headers())
            logger.info("Unregistered companion '%s'", self.settings.name)
        except httpx.HTTPError as exc:
            logger.warning("Unable to unregister companion '%s': %s", self.settings.name, exc)

    def _url(self, path: str) -> str:
        return f"{self.settings.kroki_url}{path}"

    def _headers(self) -> dict[str, str]:
        if self.settings.registration_token:
            return {"Authorization": f"Bearer {self.settings.registration_token}"}
        return {}


async def _wait(stop: asyncio.Event, timeout: float) -> bool:
    """Wait for the stop event; return True if it was set."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=timeout)
        return True
    except TimeoutError:
        return False
