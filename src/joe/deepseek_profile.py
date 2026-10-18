"""Local DeepSeek profile; reuse Codex without altering its ordinary account."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

MODELS = ("deepseek-flash", "deepseek-v4-pro")
EFFORTS = ("low", "high", "max")


def profile_directory() -> Path:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "joe" / "deepseek" / "codex"


def _api_key() -> str:
    path = profile_directory().parent / "credentials.json"
    try:
        if path.is_symlink():
            raise ValueError("credentials must be a regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("credentials must be a regular file")
            if os.name != "nt" and (
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid()
            ):
                raise ValueError("credentials must be owned by this user with mode 0600")
            text = stream.read(16_385)
            if len(text) > 16_384:
                raise ValueError("credentials file is too large")
        payload = json.loads(text)
    except (OSError, ValueError):
        # JSON/OS exceptions may retain the credential document. Never chain
        # those exceptions into a user-visible traceback.
        raise ValueError("DeepSeek credentials.json requires a protected regular file (0600)") from None
    key = payload.get("api_key") if isinstance(payload, dict) else None
    if not isinstance(key, str) or not key.strip():
        raise ValueError("DeepSeek API key is not configured")
    key = key.strip()
    if not key.isascii() or any(ord(character) < 33 or ord(character) == 127 for character in key):
        raise ValueError("DeepSeek credentials require a single ASCII API token")
    return key


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
