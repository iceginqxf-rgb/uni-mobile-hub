"""Screenshot-based JPEG screen provider for Android devices."""

from __future__ import annotations

import time
from typing import Optional

from ios.screen_provider.base_provider import BaseScreenProvider
from utils.app_errors import AppError
from utils.logging_setup import get_logger

_log = get_logger(__name__)


class AdbScreenshotProvider(BaseScreenProvider):
    """Capture JPEG frames from ``adb exec-out screencap -p`` as universal fallback."""

    name = "screenshot"

    def __init__(self, adb, udid: str, fps: int = 5, quality: int = 70) -> None:
        self.adb = adb
        self.udid = udid
        self.fps = max(1, min(15, int(fps)))
        self.quality = max(20, min(95, int(quality)))
        self._running = False
        self._healthy = False
        self._frames = 0
        self._last_tick = 0.0

    def start(self) -> None:
        self._running = True
        self._healthy = True

    def read_frame(self) -> Optional[bytes]:
        if not self._running:
            return None
        interval = 1.0 / self.fps
        now = time.monotonic()
        wait = interval - (now - self._last_tick)
        if wait > 0:
            time.sleep(wait)
        self._last_tick = time.monotonic()
        try:
            data = self.adb.screenshot_jpeg(self.udid, quality=self.quality)
            self._frames += 1
            self._healthy = True
            return data
        except AppError as exc:
            _log.warning("ADB screenshot failed for %s: %s", self.udid, exc.message)
            self._healthy = False
            return None

    def stop(self) -> None:
        self._running = False
        self._healthy = False

    def health(self) -> bool:
        return self._running and self._healthy

    @property
    def stats(self) -> dict:
        return {"provider": self.name, "frames": self._frames, "healthy": self.health()}
