"""Android device model extending :class:`services.device_models.MobileDevice`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from services.device_models import MobileDevice

ANDROID_CAPABILITIES = [
    "back",
    "home",
    "recent",
    "power",
    "wake",
    "volume",
    "rotate",
    "apk",
    "files",
    "logcat",
    "clipboard",
]


@dataclass
class AndroidDevice(MobileDevice):
    platform: str = "android"
    source: str = "android"
    capabilities: List[str] = field(default_factory=lambda: list(ANDROID_CAPABILITIES))
