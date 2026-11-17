"""
Persistent application settings service (`SettingsService`)
(services/SettingsService.py).

Stores user preferences in `data/settings.json` so settings persist across
runs and are accessible from both services and TUI screens/widgets.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from config import ROOT_DIR

SETTINGS_FILE: Path = ROOT_DIR / "data" / "settings.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "textual-dark",
    "figlet_headers": True,
    "posters_enabled": True,
    "default_tab": "tab-home",
    "page_size": 10,
    "tmdb_fallback": True,
    "public_activity": True,
    "remember_session": True,
    "last_username": "",
}


class SettingsService:
    """Singleton managing persistent application settings in `data/settings.json`."""

    _instance: Optional["SettingsService"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "SettingsService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._data: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._load()
        self._initialized = True

    def _load(self) -> None:
        if not SETTINGS_FILE.is_file():
            return
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key, default_val in DEFAULT_SETTINGS.items():
                    if key in raw:
                        self._data[key] = raw[key]
        except Exception:
            self._data = dict(DEFAULT_SETTINGS)

    def _save(self) -> None:
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULT_SETTINGS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULT_SETTINGS:
            return
        self._data[key] = value
        self._save()

    def reset_defaults(self) -> None:
        last_user = self._data.get("last_username", "")
        self._data = dict(DEFAULT_SETTINGS)
        if last_user:
            self._data["last_username"] = last_user
        self._save()

    @property
    def theme(self) -> str:
        return str(self._data.get("theme") or DEFAULT_SETTINGS["theme"])

    @property
    def figlet_headers(self) -> bool:
        return bool(self._data.get("figlet_headers", True))

    @property
    def posters_enabled(self) -> bool:
        return bool(self._data.get("posters_enabled", True))

    @property
    def default_tab(self) -> str:
        val = str(self._data.get("default_tab") or "tab-home")
        return val if val in ("tab-home", "tab-lists", "tab-explore", "tab-profile") else "tab-home"

    @property
    def page_size(self) -> int:
        try:
            val = int(self._data.get("page_size", 10))
            return val if val in (10, 20, 30) else 10
        except (TypeError, ValueError):
            return 10

    @property
    def tmdb_fallback(self) -> bool:
        return bool(self._data.get("tmdb_fallback", True))

    @property
    def public_activity(self) -> bool:
        return bool(self._data.get("public_activity", True))

    @property
    def remember_session(self) -> bool:
        return bool(self._data.get("remember_session", True))

    @property
    def last_username(self) -> str:
        return str(self._data.get("last_username") or "")
