"""User configuration: API credentials and named profiles for multiple orgs.

Config lives at ~/.hologram/config.toml. Format:

    default_profile = "personal"

    [profiles.personal]
    api_key = "..."
    org_id = 12345
    base_url = "https://dashboard.hologram.io/api/1"

API keys can also be supplied via HOLOGRAM_API_KEY env var, which overrides
the config file. If no API key is configured AND --mock is not set, network
commands fall back to mock mode automatically with a warning.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_BASE_URL = "https://dashboard.hologram.io/api/1"


@dataclass
class Profile:
    name: str
    api_key: str | None
    org_id: int | None
    base_url: str = DEFAULT_BASE_URL

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key) and self.org_id is not None


def config_path() -> Path:
    return Path(os.environ.get("HOLOGRAM_CONFIG", Path.home() / ".hologram" / "config.toml"))


def load_profile(name: str | None = None) -> Profile:
    env_key = os.environ.get("HOLOGRAM_API_KEY")
    env_org = os.environ.get("HOLOGRAM_ORG_ID")
    env_base = os.environ.get("HOLOGRAM_BASE_URL", DEFAULT_BASE_URL)

    path = config_path()
    file_data: dict = {}
    if path.exists():
        with path.open("rb") as f:
            file_data = tomllib.load(f)

    profile_name = name or file_data.get("default_profile") or "default"
    profiles = file_data.get("profiles", {})
    file_profile = profiles.get(profile_name, {})

    return Profile(
        name=profile_name,
        api_key=env_key or file_profile.get("api_key"),
        org_id=int(env_org) if env_org else file_profile.get("org_id"),
        base_url=env_base or file_profile.get("base_url", DEFAULT_BASE_URL),
    )
