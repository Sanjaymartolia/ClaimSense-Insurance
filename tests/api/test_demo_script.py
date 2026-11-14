"""scripts/demo.py, the final-review demo: all three scenes through the case API (stub, free)."""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("langgraph.checkpoint.sqlite")

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("claimsense_demo_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_demo_scene_passes_in_stub_mode(capsys):
    assert _load_demo().main(["--llm", "stub", "--tools", "stub", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out
    for scene in ("Scene 1: PASS", "Scene 2: PASS", "Scene 3: PASS"):
        assert scene in out


def test_scene_2_alone_settles_clm_0004_first(capsys):
    assert _load_demo().main(["--scene", "2", "--yes"]) == 0
    assert "Scene 2: PASS" in capsys.readouterr().out


def test_a_server_that_is_down_cannot_start():
    assert _load_demo().main(["--url", "http://127.0.0.1:9", "--yes"]) == 2
