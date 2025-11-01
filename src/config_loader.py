from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def _coerce_env(value: Optional[str], default: Optional[str] = None) -> Optional[str]:
    if not value:
        return default
    return os.getenv(value, default)


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _resolve_config_path(path: Optional[str] = None) -> Path:
    candidate = Path(path or os.getenv("APP_CONFIG_PATH", "config/agents.yaml"))
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


BASE_DIR = Path.cwd().resolve()


def _resolve_instruction_path(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(BASE_DIR):
        raise ValueError(f"Invalid instruction path outside project: {path}")
    return resolved


@dataclass
class AppConfig:
    raw: Dict[str, Any]

    @property
    def vector_store_ids(self) -> list[str]:
        return self.raw.get("vector_store", {}).get("vector_store_ids", [])

    @property
    def defaults(self) -> Dict[str, Any]:
        defaults = dict(self.raw.get("defaults", {}))
        env_map = self.raw.get("env_overrides", {}) or {}
        for key, env_name in env_map.items():
            value = _coerce_env(env_name)
            if value is not None:
                if key in {"temperature", "top_p"}:
                    value = float(value)
                elif key in {"max_tokens"}:
                    value = int(value)
                defaults[key] = value
        return defaults

    def agent_cfg(self, key: str) -> Dict[str, Any]:
        base = dict(self.defaults)
        config = dict(self.raw.get("agents", {}).get(key, {}))
        base.update({k: v for k, v in config.items() if k not in {"instructions", "instructions_file"}})

        instructions = config.get("instructions")
        instructions_file = config.get("instructions_file")
        if instructions_file:
            base["instructions"] = _read_text_file(_resolve_instruction_path(instructions_file))
        elif instructions:
            base["instructions"] = instructions
        else:
            base["instructions"] = ""
        return base

    @property
    def guardrails(self) -> Dict[str, Any]:
        return self.raw.get("guardrails", {})


_CONFIG_CACHE: Optional[AppConfig] = None
_CONFIG_CACHE_PATH: Optional[Path] = None


def _build_app_config(raw: Dict[str, Any]) -> AppConfig:
    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a mapping.")
    return AppConfig(raw)


def load_app_config(path: Optional[str] = None, *, force_reload: bool = False) -> AppConfig:
    global _CONFIG_CACHE, _CONFIG_CACHE_PATH  # pylint: disable=global-statement

    if os.getenv("APP_CONFIG_JSON"):
        raw = json.loads(os.environ["APP_CONFIG_JSON"])
        config = _build_app_config(raw)
        _CONFIG_CACHE = config
        _CONFIG_CACHE_PATH = None
        return config

    config_path = _resolve_config_path(path)
    if (
        not force_reload
        and _CONFIG_CACHE is not None
        and _CONFIG_CACHE_PATH is not None
        and _CONFIG_CACHE_PATH == config_path
    ):
        return _CONFIG_CACHE

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = _build_app_config(raw)
    _CONFIG_CACHE = config
    _CONFIG_CACHE_PATH = config_path
    return config


def read_config_yaml(path: Optional[str] = None) -> str:
    return _resolve_config_path(path).read_text(encoding="utf-8")


def save_app_config(raw: Dict[str, Any], path: Optional[str] = None) -> AppConfig:
    config_path = _resolve_config_path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    config = _build_app_config(raw)
    global _CONFIG_CACHE, _CONFIG_CACHE_PATH  # pylint: disable=global-statement
    _CONFIG_CACHE = config
    _CONFIG_CACHE_PATH = config_path
    return config


def save_app_config_from_yaml(yaml_text: str, path: Optional[str] = None) -> AppConfig:
    raw = yaml.safe_load(yaml_text)
    if not isinstance(raw, dict):
        raise ValueError("Configuration YAML must define a mapping at the root.")
    return save_app_config(raw, path=path)


def list_instruction_files(config: AppConfig) -> list[str]:
    files: set[str] = set()
    for agent in (config.raw.get("agents") or {}).values():
        if isinstance(agent, dict):
            instr = agent.get("instructions_file")
            if instr:
                files.add(instr)
    return sorted(files)


def read_instruction_files(paths: list[str]) -> Dict[str, str]:
    contents: Dict[str, str] = {}
    for rel_path in paths:
        resolved = _resolve_instruction_path(rel_path)
        if resolved.exists():
            contents[rel_path] = resolved.read_text(encoding="utf-8")
        else:
            contents[rel_path] = ""
    return contents


def write_instruction_files(payload: Dict[str, str]) -> None:
    for rel_path, content in payload.items():
        resolved = _resolve_instruction_path(rel_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")


def clear_app_config_cache() -> None:
    global _CONFIG_CACHE, _CONFIG_CACHE_PATH  # pylint: disable=global-statement
    _CONFIG_CACHE = None
    _CONFIG_CACHE_PATH = None
