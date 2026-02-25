"""Configuration management — TOML config at ~/.config/circuitai/circuit.toml."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import tomli_w

from circuitai.core.exceptions import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "data_dir": "~/.local/share/circuitai",
        "first_run": True,
    },
    "security": {
        "keyring_enabled": False,
        "pbkdf2_iterations": 256_000,
    },
    "display": {
        "date_format": "%Y-%m-%d",
        "currency_symbol": "$",
        "color_theme": "default",
    },
    "calendar": {
        "enabled": False,
        "server_url": "",
        "username": "",
        "calendar_name": "CircuitAI",
        "sync_interval_minutes": 30,
        "sync_bills": True,
        "sync_deadlines": True,
        "sync_activities": True,
    },
}


def get_config_dir() -> Path:
    """Return the config directory, creating it if needed."""
    config_dir = Path(os.environ.get("CIRCUITAI_CONFIG_DIR", "~/.config/circuitai")).expanduser()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    """Return the path to the config TOML file."""
    return get_config_dir() / "circuit.toml"


def get_data_dir(config: dict[str, Any] | None = None) -> Path:
    """Return the data directory, creating it if needed."""
    if config is None:
        config = load_config()
    data_dir = Path(config.get("general", {}).get("data_dir", "~/.local/share/circuitai")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_history_path() -> Path:
    """Return the path to the REPL history file."""
    return get_config_dir() / "history"


def load_config() -> dict[str, Any]:
    """Load configuration from TOML file, returning defaults if not found."""
    config_path = get_config_path()
    if not config_path.exists():
        return _deep_copy_dict(_DEFAULT_CONFIG)
    try:
        with open(config_path, "rb") as f:
            user_config = tomllib.load(f)
        return _merge_config(_deep_copy_dict(_DEFAULT_CONFIG), user_config)
    except Exception as e:
        raise ConfigError(f"Failed to load config: {e}") from e


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to TOML file."""
    config_path = get_config_path()
    try:
        with open(config_path, "wb") as f:
            tomli_w.dump(config, f)
    except Exception as e:
        raise ConfigError(f"Failed to save config: {e}") from e


def update_config(**updates: Any) -> dict[str, Any]:
    """Load config, apply nested updates, save, and return the result.

    Usage: update_config(general={"first_run": False}, security={"keyring_enabled": True})
    """
    config = load_config()
    for section, values in updates.items():
        if section not in config:
            config[section] = {}
        if isinstance(values, dict):
            config[section].update(values)
        else:
            config[section] = values
    save_config(config)
    return config


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _merge_config(base[key], value)
        else:
            base[key] = value
    return base


def _deep_copy_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Simple deep copy for nested dicts of simple types."""
    result: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _deep_copy_dict(v)
        else:
            result[k] = v
    return result
