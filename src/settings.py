"""Persistent settings management for HIVE_Extract.

settings.json stores non-secret configuration only.
The Hive API key is stored in the OS keyring (Service: "BosOpt",
Username: "Hive-APIKey") and loaded at runtime.
All other config (workspace_id, user_id, spreadsheet IDs, webhooks)
comes from the shared MasterConfig.
"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import keyring


# Shared config directory (sibling to this project)
SHARED_CONFIG_DIR = Path(__file__).parent.parent.parent / "_shared_config"


KEYRING_SERVICE = "BosOpt"
KEYRING_USERNAME = "Hive-APIKey"


@dataclass
class AppSettings:
    """Application settings.

    The Hive API key is read from the OS keyring (not settings.json).
    workspace_id, user_id, webhook URLs, etc. come from MasterConfig.
    """

    hive_api_key: str = ""
    configuration_name: str = "HIVE_Extract"

    def is_configured(self) -> bool:
        """Check if required local settings are present."""
        return bool(self.hive_api_key)


_SHARED_APP_DIR = SHARED_CONFIG_DIR / "apps" / "HIVE_Extract"


def get_config_dir() -> Path:
    """Get the app config directory in _shared_config."""
    return _SHARED_APP_DIR


def get_settings_path() -> Path:
    """Get the settings.json file path."""
    return _SHARED_APP_DIR / "settings.json"


def load_settings() -> AppSettings:
    """Load settings from settings.json and API key from OS keyring."""
    settings_path = get_settings_path()

    configuration_name = "HIVE_Extract"
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                configuration_name = data.get("configuration_name", "HIVE_Extract")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load settings: {e}")

    # Read API key from OS keyring
    api_key = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) or ""

    return AppSettings(
        hive_api_key=api_key,
        configuration_name=configuration_name,
    )


def save_settings(settings: AppSettings) -> None:
    """Save settings to settings.json (non-secret fields only).

    The API key is saved to the OS keyring, NOT to settings.json.
    """
    _SHARED_APP_DIR.mkdir(parents=True, exist_ok=True)

    settings_path = get_settings_path()

    # Only write non-secret fields to settings.json
    data = {"configuration_name": settings.configuration_name}
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Store API key in OS keyring
    if settings.hive_api_key:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, settings.hive_api_key)


def ensure_config_dir() -> Path:
    """Ensure the app config directory exists and return its path."""
    _SHARED_APP_DIR.mkdir(parents=True, exist_ok=True)
    return _SHARED_APP_DIR


def get_credentials_path(credential_ref: str = "BosOpt") -> Path:
    """Get the credentials.json file path for Google OAuth.

    Args:
        credential_ref: Client folder name. Defaults to BosOpt (shared Google auth).
                       Only override via google_auth_override in MasterConfig.
    """
    return SHARED_CONFIG_DIR / "clients" / credential_ref / "credentials.json"


def get_token_path(credential_ref: str = "BosOpt") -> Path:
    """Get the token.json file path for Google OAuth.

    Args:
        credential_ref: Client folder name. Defaults to BosOpt (shared Google auth).
                       Only override via google_auth_override in MasterConfig.
    """
    return SHARED_CONFIG_DIR / "clients" / credential_ref / "token.json"
