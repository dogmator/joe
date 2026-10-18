"""Local DeepSeek profile; reuse Codex without altering its ordinary account."""

from __future__ import annotations

import json
import os
from pathlib import Path

MODELS = ("deepseek-flash", "deepseek-v4-pro")
EFFORTS = ("low", "high", "max")


def profile_directory() -> Path:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "joe" / "deepseek" / "codex"


def _api_key() -> str:
    path = profile_directory().parent / "credentials.json"
    if path.is_symlink():
        raise ValueError("DeepSeek credentials must be a separate regular file")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("DeepSeek credentials.json requires permissions 0600")
    payload = json.loads(path.read_text(encoding="utf-8"))
    key = payload.get("api_key") if isinstance(payload, dict) else None
    if not isinstance(key, str) or not key.strip():
        raise ValueError("DeepSeek API key is not configured")
    return key.strip()


def setup_error() -> str | None:
    try:
        directory = profile_directory()
        if not (directory / "config.toml").is_file():
            return "DeepSeek requires an isolated Codex config.toml"
        if not (directory / "models.json").is_file():
            return "DeepSeek requires its local models.json catalogue"
        _api_key()
        payload = json.loads((directory / "models.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            return "DeepSeek models.json is invalid"
        if not any(
            isinstance(item, dict) and item.get("slug") in MODELS for item in payload["models"]
        ):
            return "DeepSeek models.json contains no supported model"
    except (OSError, ValueError):
        return "DeepSeek profile or protected API key requires setup (credentials.json: 0600)"
    return None


def process_environment(parent: dict[str, str]) -> dict[str, str]:
    environment = dict(parent)
    environment["CODEX_HOME"] = str(profile_directory())
    environment["DEEPSEEK_API_KEY"] = _api_key()
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
        environment.pop(name, None)
    return environment
