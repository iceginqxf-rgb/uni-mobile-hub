"""iOS device model extending :class:`services.device_models.MobileDevice`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from services.device_models import MobileDevice

IOS_CAPABILITIES = [
    "home",
    "lock",
    "unlock",
    "volume",
    "assistivetouch",
    "voiceover",
    "zoom",
    "ipa",
    "afc",
    "syslog",
]


@dataclass
class IOSDevice(MobileDevice):
    platform: str = "ios"
    source: str = "ios"
    capabilities: List[str] = field(default_factory=lambda: list(IOS_CAPABILITIES))

    @staticmethod
    def from_pymobiledevice3_output(info: dict) -> "IOSDevice":
        """Build from a ``pymobiledevice3 usbmux list`` / lockdown info dict.

        Field names vary across pymobiledevice3 versions, so we probe several
        common aliases and degrade gracefully (missing → empty/unknown).
        """
        def pick(*keys, default=""):
            for k in keys:
                v = info.get(k)
                if v not in (None, ""):
                    return v
            return default

        udid = pick("Identifier", "UniqueDeviceID", "udid", "SerialNumber")
        name = pick("DeviceName", "Name", "name")
        product_type = pick("ProductType", "product_type")
        ios_version = pick("ProductVersion", "ios_version", "os_version")
        # Being in ``usbmux list`` means the device is plugged in & paired
        # (trusted/reachable) — but NOT app-level connected. ``connected`` must
        # stay False here and only flip True after adapter.connect() brings up
        # the WDA forward; otherwise the UI thinks it's already connected and
        # skips connect(), so WebDriverAgent never launches.
        reachable = bool(pick("ConnectionType", "connected", default="")) or bool(udid)
        return IOSDevice(
            udid=str(udid),
            name=str(name) or str(udid),
            product_type=str(product_type),
            ios_version=str(ios_version),
            os_version=str(ios_version),
            connected=False,
            trusted=bool(info.get("trusted", reachable)),
        )
