"""Experiment configs: one YAML file per condition, all conditions of an experiment run by one
harness (`run.py`). A config never holds a model ID: it names a role in `config/models.yaml`.

Each experiment names the one field its conditions may differ in (`varies`): E1 the
`architecture`, E2 the `defence`, E4 the `arithmetic`. Everything else must match, or the
comparison would not isolate that field. E3 (Reflexion) has its own runner, `e3.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from eval.harness.loader import REPO_ROOT

CONFIG_DIR = Path(__file__).resolve().parent / "configs"
MODELS_YAML = REPO_ROOT / "config" / "models.yaml"

ARCHITECTURES = ("fixed", "single_agent", "team")
#: E2. Names match the security scoreboard's rows (eval/security/scoreboard.py).
DEFENCES = ("none", "input", "input+scan", "input+guard_model")
#: E4, the signature ablation: who computes the rupees.
ARITHMETIC = ("calculator", "llm")
MEASURES = ("harness", "security")
CONDITION_KEYS = ("architecture", "defence", "arithmetic")

REQUIRED = (
    "experiment",
    "condition",
    "architecture",
    "description",
    "model_role",
    "tools",
    "budget",
    "data",
    "calculator",
    "retrieval",
)


class ConfigError(ValueError):
    """A config that cannot run, or an experiment whose conditions are not comparable."""


@dataclass(frozen=True)
class Budget:
    max_tool_calls_per_claim: int
    max_cost_usd_per_claim: float


@dataclass(frozen=True)
class ExperimentConfig:
    path: Path
    experiment: str
    condition: str
    architecture: str
    description: str
    model_role: str
    model: str  # resolved from config/models.yaml
    tools: tuple[str, ...]
    budget: Budget
    splits: tuple[str, ...]
    pass_documents: bool
    calculator: str
    retrieval: str
    varies: tuple[str, ...] = ("architecture",)
    measure: str = "harness"
    defence: str = "input"
    arithmetic: str = "calculator"

    def shared(self) -> dict[str, Any]:
        """What every condition of the experiment must agree on."""
        fixed = {k: getattr(self, k) for k in CONDITION_KEYS if k not in self.varies}
        return {
            "model": self.model,
            "tools": self.tools,
            "budget": self.budget,
            "splits": self.splits,
            "pass_documents": self.pass_documents,
            "calculator": self.calculator,
            "retrieval": self.retrieval,
            "varies": self.varies,
            "measure": self.measure,
            **fixed,
        }


def resolve_model(role: str, models_yaml: Path = MODELS_YAML) -> str:
    models = (yaml.safe_load(models_yaml.read_text(encoding="utf-8")) or {}).get("models") or {}
    if role not in models:
        raise ConfigError(f"model_role {role!r} is not in {models_yaml} (have {sorted(models)})")
    return str(models[role])


def _check(path: Path, cfg: ExperimentConfig) -> None:
    name = path.name
    if cfg.architecture not in ARCHITECTURES:
        raise ConfigError(f"{name}: architecture must be one of {ARCHITECTURES}")
    if cfg.defence not in DEFENCES or cfg.arithmetic not in ARITHMETIC:
        raise ConfigError(f"{name}: defence is one of {DEFENCES}, arithmetic one of {ARITHMETIC}")
    if cfg.measure not in MEASURES:
        raise ConfigError(f"{name}: measure must be one of {MEASURES}")
    if not cfg.varies or any(v not in CONDITION_KEYS for v in cfg.varies):
        raise ConfigError(f"{name}: varies must name fields from {CONDITION_KEYS}")
    if cfg.calculator not in ("real", "reference") or cfg.retrieval not in ("stub", "real"):
        raise ConfigError(f"{name}: calculator is real|reference, retrieval is stub|real")
    team_only = cfg.measure == "security" or cfg.arithmetic == "llm" or cfg.defence != "input"
    if team_only and cfg.architecture != "team":
        raise ConfigError(f"{name}: defences and LLM arithmetic apply to the team architecture")
    if cfg.arithmetic == "llm" and cfg.calculator != "real":
        raise ConfigError(
            f"{name}: arithmetic llm replaces the real calculator; set calculator real"
        )


def load(path: Path | str, models_yaml: Path = MODELS_YAML) -> ExperimentConfig:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise ConfigError(f"{path.name}: missing {missing}")
    if "model" in raw:
        raise ConfigError(f"{path.name}: name a model_role, never a model ID (config/models.yaml)")
    budget = raw["budget"] or {}
    data = raw["data"] or {}
    cfg = ExperimentConfig(
        path=path,
        experiment=str(raw["experiment"]),
        condition=str(raw["condition"]),
        architecture=str(raw["architecture"]),
        description=" ".join(str(raw["description"]).split()),
        model_role=str(raw["model_role"]),
        model=resolve_model(str(raw["model_role"]), models_yaml),
        tools=tuple(raw["tools"]),
        budget=Budget(
            int(budget["max_tool_calls_per_claim"]), float(budget["max_cost_usd_per_claim"])
        ),
        splits=tuple(data.get("splits") or ("dev",)),
        pass_documents=bool(data.get("pass_documents", True)),
        calculator=str(raw["calculator"]),
        retrieval=str(raw["retrieval"]),
        varies=tuple(raw.get("varies") or ("architecture",)),
        measure=str(raw.get("measure", "harness")),
        defence=str(raw.get("defence", "input")),
        arithmetic=str(raw.get("arithmetic", "calculator")),
    )
    _check(path, cfg)
    return cfg


def load_experiment(
    name: str, config_dir: Path = CONFIG_DIR, models_yaml: Path = MODELS_YAML
) -> list[ExperimentConfig]:
    """Every config of one experiment, sorted by condition. Refuses conditions that differ in
    anything but the experiment's `varies` field: then the comparison would not isolate it."""
    if name == "E3":
        raise ConfigError("E3 (Reflexion) has its own runner: python -m eval.experiments.e3")
    configs = [load(p, models_yaml) for p in sorted(config_dir.glob(f"{name}_*.yaml"))]
    if not configs:
        raise ConfigError(f"no configs for {name!r} in {config_dir}")
    if any(c.experiment != name for c in configs):
        raise ConfigError(f"a {name}_*.yaml file names another experiment")
    conditions = [c.condition for c in configs]
    if len(set(conditions)) != len(conditions):
        raise ConfigError(f"{name}: duplicate condition in {conditions}")
    first = configs[0]
    for other in configs[1:]:
        for key, value in first.shared().items():
            if other.shared().get(key) != value:
                raise ConfigError(
                    f"{name}: {other.path.name} differs from {first.path.name} in {key!r}; "
                    f"only {list(first.varies)} may change between conditions"
                )
    return sorted(configs, key=lambda c: c.condition)
