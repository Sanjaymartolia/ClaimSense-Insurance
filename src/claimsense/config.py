"""Loads config/models.yaml — the single place for model IDs and prompt versions (L16)."""

import os
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(os.environ.get("CLAIMSENSE_CONFIG", "config/models.yaml"))


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
