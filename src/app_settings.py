"""Helpers to load shared application settings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_SETTINGS_PATH = "config/app_settings.yaml"


class SettingsLoadError(RuntimeError):
    """Raised when the settings file contains an unexpected payload."""


@lru_cache(maxsize=1)
def _load_settings(path_str: str) -> Dict[str, Any]:
    """Load the YAML settings file from the provided path."""
    path = Path(path_str)
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise SettingsLoadError(
            f"Settings file {path} must contain a YAML object at the root."
        )
    return data


def get_app_settings() -> Dict[str, Any]:
    """Return the parsed application settings."""
    path = os.getenv("APP_SETTINGS_PATH", DEFAULT_SETTINGS_PATH)
    return _load_settings(path)


def get_settings_section(section: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Return a subsection of the settings, falling back to default if missing."""
    settings = get_app_settings()
    if section in settings and isinstance(settings[section], dict):
        return settings[section]
    return default or {}
