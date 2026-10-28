"""Every setting in one place. Override any of them for one run without editing:

RETRIEVAL_MODE=hybrid TOP_K=6 python scripts/evaluate_dev.py --label hybrid_k6
"""

import os
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parent.parent  # your folder: course/ or exercises/<you>/
REPO = next(p for p in KIT.parents if (p / "pyproject.toml").exists())

# shared data — read it, never edit it (data/README.md, ADR-0002)
KB_FILE = REPO / "data/knowledge_base/policy_knowledge_base.jsonl"
DEV_CLAIMS = REPO / "eval/golden_dev/claims.jsonl"
DEV_GOLD = REPO / "eval/golden_dev/gold_worksheets.jsonl"  # for scoring only, never in a prompt
RETRIEVAL_GOLD = REPO / "eval/golden_dev/retrieval_queries.jsonl"
REDTEAM_CLAIMS = REPO / "eval/redteam/claims.jsonl"  # 30 attacked claims (build_cases.py)
REDTEAM_GOLD = REPO / "eval/redteam/gold.jsonl"

# your own scratch space (gitignored)
INDEX_DIR, CACHE_DIR = KIT / ".index", KIT / ".cache"
STATE_DB, RUNS_DIR = KIT / ".state/checkpoints.sqlite", KIT / "runs"


def _env(name, default, cast=str):
    raw = os.environ.get(name)
    if raw is None:
        return default
    if cast is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return cast(raw)


# models: never hard-code an id; they live in config/models.yaml (CLAUDE.md)
_MODELS = yaml.safe_load((REPO / "config/models.yaml").read_text(encoding="utf-8"))
TOOL_MODEL = _env("TOOL_MODEL", _MODELS["models"]["coverage"])  # must support tool calling
CHECK_MODEL = _env("CHECK_MODEL", _MODELS["models"]["critic"])  # TODO 3 uses this one
EMBED_MODEL = _env("EMBED_MODEL", _MODELS["embeddings"])
TEMPERATURE = _env("TEMPERATURE", float(_MODELS["temperature"]["default"]), float)
MAX_TOKENS = _env("MAX_TOKENS", 900, int)
LLM_CACHE = _env("LLM_CACHE", True, bool)  # same request twice = free; delete .cache/ to refresh

# retrieval
RETRIEVAL_MODE = _env("RETRIEVAL_MODE", "dense")  # dense | hybrid (TODO 2)
CHUNK_STRATEGY = _env("CHUNK_STRATEGY", "fixed")  # fixed | clauses (TODO 1)
TOP_K = _env("TOP_K", 4, int)  # pieces the model sees
CANDIDATE_K = _env("CANDIDATE_K", 8, int)  # pieces fetched before narrowing down
CHUNK_SIZE = _env("CHUNK_SIZE", 600, int)
CHUNK_OVERLAP = _env("CHUNK_OVERLAP", 150, int)
RRF_K = _env("RRF_K", 60, int)

# The excluded-items list is a SUPPORTING reference. It never outranks the policy
# wording, and citing it alone is not a source (see metrics.py, TODO 2d).
SUPPORTING_RECORD_TYPE = "excluded_items_reference"

# runtime
MAX_TOOL_STEPS = _env("MAX_TOOL_STEPS", 8, int)  # stops the tool loop running forever
ROUTES = ("ready_for_approval", "needs_review")
