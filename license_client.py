import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Accept either naive ISO or timezone-aware ISO.
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def get_machine_fingerprint() -> str:
    # Stable-enough fingerprint for licensing (not a security boundary).
    parts: list[str] = []

    # Windows MachineGuid if accessible.
    try:
        if platform.system().lower() == "windows":
            import winreg  # type: ignore

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                guid, _ = winreg.QueryValueEx(k, "MachineGuid")
                parts.append(f"machineguid:{guid}")
    except Exception:
        pass

    try:
        parts.append(f"node:{platform.node()}")
    except Exception:
        pass
    try:
        parts.append(f"platform:{platform.platform()}")
    except Exception:
        pass
    try:
        parts.append(f"py:{sys.version.split()[0]}")
    except Exception:
        pass

    return "|".join(parts) or "unknown"


@dataclass
class LicenseStatus:
    ok: bool
    message: str
    expires_at: datetime | None = None
    token_present: bool = False


class LicenseClient:
    def __init__(self, server_url: str, cache_path: str, app_version: str):
        self.server_url = (server_url or "").rstrip("/")
        self.cache_path = cache_path
        self.app_version = app_version
        self.fingerprint = get_machine_fingerprint()

    def _load_cache(self) -> dict:
        try:
            if os.path.exists(self.cache_path):
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            return {}
        return {}

    def _save_cache(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _is_cache_valid_now(self, cache: dict) -> tuple[bool, datetime | None]:
        expires_at = _parse_dt(cache.get("expires_at"))
        if not expires_at:
            return False, None
        return _utcnow() < expires_at, expires_at

    def cached_status(self) -> LicenseStatus:
        cache = self._load_cache()
        ok, expires_at = self._is_cache_valid_now(cache)
        token = cache.get("token")
        if ok and token:
            return LicenseStatus(ok=True, message="License valid (cached)", expires_at=expires_at, token_present=True)
        if token and expires_at:
            return LicenseStatus(ok=False, message="License expired (cached)", expires_at=expires_at, token_present=True)
        return LicenseStatus(ok=False, message="Not activated", expires_at=None, token_present=bool(token))

    def validate_online(self, timeout_s: int = 10) -> LicenseStatus:
        cache = self._load_cache()
        token = cache.get("token")
        if not token:
            return LicenseStatus(ok=False, message="No activation token", token_present=False)
        if not self.server_url:
            return LicenseStatus(ok=False, message="Missing license server URL", token_present=True)

        try:
            r = requests.post(
                f"{self.server_url}/validate",
                json={"token": token, "fingerprint": self.fingerprint, "app_version": self.app_version},
                timeout=timeout_s,
            )
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code != 200:
                return LicenseStatus(ok=False, message=data.get("error") or f"Validate failed ({r.status_code})", token_present=True)

            if not data.get("ok"):
                return LicenseStatus(ok=False, message=data.get("error") or "License invalid", token_present=True)

            expires_at = _parse_dt(data.get("expires_at"))
            cache["expires_at"] = expires_at.isoformat() if expires_at else None
            cache["last_validated"] = _utcnow().isoformat()
            self._save_cache(cache)
            return LicenseStatus(ok=True, message="License valid (online)", expires_at=expires_at, token_present=True)
        except Exception:
            return LicenseStatus(ok=False, message="License server unreachable", token_present=True)

    def activate(self, license_key: str, timeout_s: int = 10) -> LicenseStatus:
        if not self.server_url:
            return LicenseStatus(ok=False, message="Missing license server URL", token_present=False)
        if not license_key:
            return LicenseStatus(ok=False, message="Empty license key", token_present=False)

        try:
            r = requests.post(
                f"{self.server_url}/activate",
                json={
                    "license_key": license_key,
                    "fingerprint": self.fingerprint,
                    "app_version": self.app_version,
                },
                timeout=timeout_s,
            )
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code != 200:
                return LicenseStatus(ok=False, message=data.get("error") or f"Activate failed ({r.status_code})", token_present=False)
            if not data.get("ok"):
                return LicenseStatus(ok=False, message=data.get("error") or "Activation rejected", token_present=False)

            token = data.get("token")
            expires_at = _parse_dt(data.get("expires_at"))
            if not token:
                return LicenseStatus(ok=False, message="Activation response missing token", token_present=False)

            cache = {
                "token": token,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "activated_at": _utcnow().isoformat(),
                "last_validated": _utcnow().isoformat(),
            }
            self._save_cache(cache)
            return LicenseStatus(ok=True, message="Activated", expires_at=expires_at, token_present=True)
        except Exception:
            return LicenseStatus(ok=False, message="License server unreachable", token_present=False)

    def allow_start_with_grace(self, grace_days: int = 7) -> bool:
        cache = self._load_cache()
        ok_now, _ = self._is_cache_valid_now(cache)
        if ok_now:
            return True
        last_validated = _parse_dt(cache.get("last_validated"))
        if not last_validated:
            return False
        return _utcnow() < (last_validated + timedelta(days=grace_days))

