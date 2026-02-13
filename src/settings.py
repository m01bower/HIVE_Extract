"""Persistent settings management for HIVE_Extract."""

import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class AppSettings:
    """Application settings stored in settings.json."""

    hive_api_key: str = ""
    hive_user_id: str = ""
    hive_workspace_id: str = ""
    configuration_name: str = "HIVE_Extract"
    google_chat_webhook_url: str = ""

    def is_configured(self) -> bool:
        """Check if required settings are present."""
        return bool(self.hive_api_key and self.hive_user_id and self.hive_workspace_id)


def get_config_dir() -> Path:
    """Get the config directory path."""
    src_dir = Path(__file__).parent
    project_root = src_dir.parent
    return project_root / "config"


def get_settings_path() -> Path:
    """Get the settings.json file path."""
    return get_config_dir() / "settings.json"


def load_settings() -> AppSettings:
    """Load settings from settings.json, returning defaults if not found."""
    settings_path = get_settings_path()

    if not settings_path.exists():
        return AppSettings()

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return AppSettings(
                hive_api_key=data.get("hive_api_key", ""),
                hive_user_id=data.get("hive_user_id", ""),
                hive_workspace_id=data.get("hive_workspace_id", ""),
                configuration_name=data.get("configuration_name", "HIVE_Extract"),
                google_chat_webhook_url=data.get("google_chat_webhook_url", ""),
            )
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load settings: {e}")
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    """Save settings to settings.json."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    settings_path = get_settings_path()

    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, indent=2)


def ensure_config_dir() -> Path:
    """Ensure the config directory exists and return its path."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_credentials_path() -> Path:
    """Get the credentials.json file path."""
    return get_config_dir() / "credentials.json"


def get_token_path() -> Path:
    """Get the token.json file path."""
    return get_config_dir() / "token.json"
