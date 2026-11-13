"""Model IDs live only in config/models.yaml (L16): the agents read them from there (AGT-09)."""

import os

import pytest
import yaml

from claimsense import config
from claimsense.agents import llm


def _configured() -> dict:
    return yaml.safe_load(config.config_path().read_text(encoding="utf-8"))["models"]


def test_every_agent_role_takes_its_model_from_the_config():
    configured = _configured()
    for role in llm.ROLES:
        assert llm.MODELS[role] == os.getenv(f"CLAIMSENSE_MODEL_{role.upper()}", configured[role])


def test_an_environment_override_changes_one_role_only(monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_MODEL_CRITIC", "test/critic-model")
    models = llm._models()
    assert models["critic"] == "test/critic-model"
    assert models["coverage"] == os.getenv("CLAIMSENSE_MODEL_COVERAGE", _configured()["coverage"])


def test_the_config_is_found_from_a_subfolder(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAIMSENSE_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    found = config.config_path()
    assert found.exists() and found.name == "models.yaml"


def test_a_config_without_an_agent_role_is_refused(monkeypatch, tmp_path):
    broken = tmp_path / "models.yaml"
    broken.write_text("models:\n  coverage: x/y\n", encoding="utf-8")
    monkeypatch.setenv("CLAIMSENSE_CONFIG", str(broken))
    with pytest.raises(RuntimeError, match="no model for"):
        llm._models()
