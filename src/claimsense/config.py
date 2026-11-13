"""Loads config/models.yaml — the single place for model IDs and prompt versions (L16)."""

import os
from functools import lru_cache
from pathlib import Path

import yaml


def config_path() -> Path:
    """$CLAIMSENSE_CONFIG, else config/models.yaml in the working directory, else the one in this
    checkout, so a script run from a subfolder (the course kit's exercises/<name>/) still finds
    it."""
    env = os.environ.get("CLAIMSENSE_CONFIG")
    if env:
        return Path(env)
    cwd = Path("config/models.yaml")
    if cwd.exists():
        return cwd
    return Path(__file__).resolve().parents[2] / "config" / "models.yaml"


CONFIG_PATH = config_path()


@lru_cache
def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def model_for(role: str) -> str:
    return load_config()["models"][role]


def openrouter_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set (see .env.example)")
    return key
