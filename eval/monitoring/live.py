"""L13 sections 8.5 and 8.6: live traffic with a known answer, an A/B split, and an incident.

The notebook's desk gets a stream of fresh travel-grant claims while a currency tool fails and a
burst of injected text arrives. Here the stream is hospitalisation claims through the ClaimSense
pipeline:

    notebook                         ClaimSense
    -------------------------------  ---------------------------------------------------------
    fresh_claim(rng) -> text, due    ClaimSource.fresh(): a dev claim under a new id, with the
                                     human gold as the known answer
    variant_for(student)             variant_for(member): the member decides the arm, so one
                                     member never sees both behaviours
    model A vs model B               A = `v1` (pipeline as it is), B = `guarded` (the product's
                                     input guardrail in front of the graph)
    FX tool outage                   the tariff tool times out (`Fault`)
    injection burst                  the red-team injection seeds, through all three doors
    handle(c, inject)                LiveRun.handle(): run, score, export metrics, code checks

Fresh claims are built in memory and never written to disk as cases. Their gold is the human dev
gold plus the one change an attack makes (a person must look), exactly as
`eval/redteam/build_cases.py` builds the red-team set; no calculator output is ever used as gold.
`live.csv` holds one row per claim with no claim text and no member id (rule 4).
"""

from __future__ import annotations

import hashlib
import random
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from eval.agent_suite.dataset import INJECTION_CATEGORIES, Case, to_case
from eval.agent_suite.judge import JudgeUnavailableError, Structured, judge_trace, payload_checks
from eval.agent_suite.outcome import is_correct
from eval.agent_suite.suite import VARIANTS
from eval.agent_suite.trace import run_traced
from eval.harness.loader import DEV_DIR, REDTEAM_DIR, read_jsonl, strip_eval_only
from eval.harness.models import ClaimRecord, EvalCase, GoldRecord
from eval.redteam import build_cases

from .metrics import Metrics, outcome_of

#: A/B label -> the agent-suite variant behind it.
ARMS: dict[str, str] = {"A": "v1", "B": "guarded"}

#: Synthetic members the traffic is spread over. With only the 20 dev patients, routing by patient
#: would tie each base claim to one arm and the A/B test would compare claims, not variants.
MEMBERS = 200

#: Share of review payloads sent to the LLM judge when the judge is on (notebook: JUDGE_SAMPLE).
JUDGE_SAMPLE = 0.25

#: Payload checks that need no gold, so they could run on real traffic.
#: `injection_shown_to_reviewer` is left out: it needs to know the claim was attacked.
GOLD_FREE_CHECKS: frozenset[str] = frozenset(
    {
        "every_deduction_cites_clause",
        "cited_clauses_exist",
        "totals_add_up",
        "route_matches_findings",
    }
)

#: Columns of `live.csv`, in order. No claim text, no member id.
RECORD_FIELDS: tuple[str, ...] = (
    "n",
    "t",
    "phase",
    "claim_id",
    "base_claim_id",
    "arm",
    "variant",
    "attacked",
    "attack_id",
    "door",
    "outcome",
    "route",
    "correct",
    "seconds",
    "llm_calls",
    "tokens",
    "cost_usd",
    "tool_calls",
    "tool_errors",
    "payload_ok",
    "judge",
    "error",
)

Log = Callable[[str], None]


# ------------------------------------------------------------------------------ fresh claims
@dataclass(frozen=True)
class LiveClaim:
    case: Case
    member: str  # the A/B routing key. Never logged, never a metric label
    base_claim_id: str
    attacked: bool


def variant_for(member: str) -> str:
    """Stable A/B arm for a member: the same member always gets the same arm."""
    digest = hashlib.md5(member.encode(), usedforsecurity=False).hexdigest()
    return "A" if int(digest, 16) % 2 == 0 else "B"


class ClaimSource:
    """The 20 dev claims, their human gold and the injection seeds, loaded once."""

    def __init__(self, members: int = MEMBERS) -> None:
        self._claims = {c["claim_id"]: c for c in read_jsonl(DEV_DIR / "claims.jsonl")}
        self._gold = {g["claim_id"]: g for g in read_jsonl(DEV_DIR / "gold_worksheets.jsonl")}
        self.bases: tuple[str, ...] = tuple(self._claims)
        #: Seeds that plant an instruction in a document or bill line (RT-001, 007, 009-012).
        self.seeds: tuple[dict, ...] = tuple(
            a
            for a in read_jsonl(REDTEAM_DIR / "attacks.jsonl")
            if a.get("type") in INJECTION_CATEGORIES and a.get("document_text")
        )
        self.members: tuple[str, ...] = tuple(f"SYN-MEM-{i:04d}" for i in range(1, members + 1))

    def build(
        self, base: str, n: int, member: str, seed: dict | None = None, door: str | None = None
    ) -> LiveClaim:
        """One fresh claim: dev claim `base` under a new id and member, optionally attacked."""
        new_id = f"LIVE-{n:06d}"
        claim = build_cases.renamed(self._claims[base], base, new_id)  # a deep copy
        gold = build_cases.renamed(self._gold[base], base, new_id)
        old_member = (claim.get("policyholder") or {}).get("synthetic_person_id")
        if old_member:
            claim = build_cases.renamed(claim, old_member, member)
        if seed is not None:
            # Gold = the human dev gold + the one change the attack makes (a person must look).
            build_cases.attack(claim, gold, seed, door, 0)
            gold.update(base_claim_id=base, door=door)
        eval_case = EvalCase(
            claim=ClaimRecord.model_validate(strip_eval_only(claim)),
            gold=GoldRecord.model_validate(gold),
            split="redteam" if seed is not None else "dev",
        )
        return LiveClaim(to_case(eval_case), member, base, seed is not None)

    def fresh(self, rng: random.Random, n: int, inject_rate: float = 0.0) -> LiveClaim:
        """A random fresh claim; with probability `inject_rate` it carries an injection."""
        base = rng.choice(self.bases)
        member = rng.choice(self.members)
        if self.seeds and rng.random() < inject_rate:
            return self.build(
                base, n, member, rng.choice(self.seeds), rng.choice(build_cases.DOORS)
            )
        return self.build(base, n, member)


# ------------------------------------------------------------------------- faults and phases
@dataclass(frozen=True)
class Fault:
    """A tool that answers slowly and then, most of the time, not at all (notebook: FAULTS)."""

    tool: str = "tariff_range"
    error_rate: float = 0.7
    delay_s: float = 1.5

    def hook(
        self, rng: random.Random, sleep: Callable[[float], None] = time.sleep
    ) -> Callable[[Any], None]:
        """A `prepare` hook for `run_traced`. It replaces the tool on this claim's `Services`
        before the tracing wrapper goes on, so the failure is recorded as an `error` tool span."""

        def prepare(services: Any) -> None:
            real = getattr(services, self.tool)

            def faulty(*args: Any, **kwargs: Any) -> Any:
                if self.delay_s:
                    sleep(self.delay_s)
                if rng.random() < self.error_rate:
                    raise TimeoutError(f"{self.tool}: upstream timed out (injected fault)")
                return real(*args, **kwargs)

            setattr(services, self.tool, faulty)

        return prepare


@dataclass(frozen=True)
class Phase:
    name: str
    seconds: float
    inject_rate: float = 0.02
    fault: Fault | None = None
    #: Alerts this phase is designed to raise. The run reports whether each one did (the drill).
    expect: tuple[str, ...] = ()


IDLE = Phase("idle", 0.0, 0.0)

#: Section 8.6. Four minutes: normal -> the tariff tool fails -> a burst of injections -> normal.
#: `HandledCorrectlyDrop` is not expected of the outage on purpose: about 30% of claims never
#: reach the tariff tool, so the share handled correctly falls only to about its 0.40 limit. The
#: outcome alert is the slow backstop; the tool and pipeline alerts are the ones that must fire.
SCENARIO: tuple[Phase, ...] = (
    Phase(
        "normal",
        75,
    ),
    Phase(
        "tariff outage",
        60,
        fault=Fault(),
        expect=("ToolErrorRateHigh", "PipelineErrorRateHigh"),
    ),
    Phase("injection burst", 45, inject_rate=0.40, expect=("GuardrailBurst",)),
    Phase("recovered", 45),
)


# --------------------------------------------------------------------------------- the run
class LiveRun:
    """Everything one live run shares: the metrics, the arms, the current phase and the log."""

    def __init__(
        self,
        metrics: Metrics,
        arms: dict[str, str] | None = None,
        source: ClaimSource | None = None,
        judge: Structured | None = None,
        judge_sample: float = JUDGE_SAMPLE,
        judge_limit: int = 20,
        log: Log = print,
    ) -> None:
        self.metrics = metrics
        self.arms = dict(arms or ARMS)
        unknown = sorted(set(self.arms.values()) - set(VARIANTS))
        if set(self.arms) != {"A", "B"} or unknown:
            raise ValueError(
                f"arms must map A and B to known variants ({', '.join(VARIANTS)}); got {self.arms}"
            )
        self.source = source or ClaimSource()
        self.phase: Phase = IDLE
        self.records: list[dict] = []
        self.worker_errors: Counter[str] = Counter()
        #: [(unix time, seconds)] each time no thread of this process could run for over 2 s.
        self.stalls: list[tuple[float, float]] = []
        self.log = log
        self._judge = judge
        self._judge_sample = judge_sample
        self._judge_left = judge_limit if judge is not None else 0
        self._lock = threading.Lock()
        self._n = 0

    def next_claim(self, rng: random.Random) -> LiveClaim:
        with self._lock:
            self._n += 1
            n = self._n
        return self.source.fresh(rng, n, self.phase.inject_rate)

    def handle(self, lc: LiveClaim, rng: random.Random) -> dict:
        """Run one claim on its member's arm, score it, export its metrics, keep one row."""
        phase = self.phase  # the phase the claim arrived in, even if it ends in the next one
        arm = variant_for(lc.member)
        prepare = phase.fault.hook(rng) if phase.fault else None
        self.metrics.in_flight.inc()
        try:
            t = run_traced(
                lc.case.eval_case, variant=arm, prepare=prepare, **VARIANTS[self.arms[arm]]
            )
        finally:
            self.metrics.in_flight.dec()

        # A blocked claim is scored too (the notebook leaves it out). Here the guardrail is the
        # difference between the arms, so its claims are the effect being measured.
        correct = is_correct(lc.case, t)
        checks = {k: ok for k, ok in payload_checks(lc.case, t).items() if k in GOLD_FREE_CHECKS}
        payload_ok = all(checks.values()) if checks else None
        verdict = self._maybe_judge(t, rng)

        # The row is complete before any metric moves, so Prometheus and live.csv always agree.
        record = {
            "n": int(lc.case.claim_id.rsplit("-", 1)[-1]),
            "t": round(time.time(), 3),
            "phase": phase.name,
            "claim_id": lc.case.claim_id,
            "base_claim_id": lc.base_claim_id,
            "arm": arm,
            "variant": self.arms[arm],
            "attacked": lc.attacked,
            "attack_id": lc.case.attack_id or "",
            "door": lc.case.door or "",
            "outcome": outcome_of(t),
            "route": t.route or "",
            "correct": correct,
            "seconds": round(t.seconds, 4),
            "llm_calls": t.llm_calls,
            "tokens": t.tokens,
            "cost_usd": round(t.cost, 6),
            "tool_calls": len(t.tool_spans),
            "tool_errors": sum(s.status == "error" for s in t.tool_spans),
            "payload_ok": payload_ok,
            "judge": verdict,
            # The exception type only: a message could quote claim text.
            "error": t.error.split(":", 1)[0] if t.error else "",
        }
        self.metrics.export_trace(t, correct)
        if payload_ok is not None:
            self.metrics.record_payload_check(arm, payload_ok)
        if verdict in ("pass", "fail"):
            self.metrics.record_judge(arm, verdict == "pass")
        with self._lock:
            self.records.append(record)
        return record

    def _maybe_judge(self, t: Any, rng: random.Random) -> str | None:
        """Send a sample of review payloads to the LLM judge. Off unless a judge was given.

        Returns "pass", "fail", "error" (the call failed: a rate limit, a timeout, a bad answer)
        or None (not sampled). A failed call never costs the claim its row.
        """
        judge = self._judge  # another worker may switch it off meanwhile
        if judge is None or not t.review_payloads or rng.random() >= self._judge_sample:
            return None
        with self._lock:
            if self._judge_left <= 0:
                return None
            self._judge_left -= 1
        try:
            verdict = judge_trace(t, judge)
        except JudgeUnavailableError as e:
            self._judge = None
            self.log(f"judge switched off: {e}")
            return None
        except Exception as e:  # noqa: BLE001 - one failed judge call must not drop the claim
            self.log(f"judge call failed: {type(e).__name__}")  # type only: no claim text
            return "error"
        return None if verdict is None else verdict.verdict

    def traffic(
        self, stop: threading.Event, seed: int, pace: tuple[float, float] = (0.2, 1.0)
    ) -> None:
        """One worker: a claim, a short pause, the next claim, until told to stop."""
        rng = random.Random(seed)  # noqa: S311 - simulated traffic, not a security decision
        while not stop.is_set():
            try:
                self.handle(self.next_claim(rng), rng)
            except Exception as e:  # noqa: BLE001 - one bad claim must not stop the traffic
                with self._lock:
                    self.worker_errors[type(e).__name__] += 1
                self.log(f"worker error: {type(e).__name__}")
            stop.wait(rng.uniform(*pace))


def phase_counts(records: Sequence[dict], phase: str) -> dict[str, Any]:
    """What happened to the claims that arrived in one phase."""
    rows = [r for r in records if r["phase"] == phase]
    return {
        "claims": len(rows),
        "correct": sum(bool(r["correct"]) for r in rows),
        "blocked": sum(r["outcome"] == "blocked" for r in rows),
        "errors": sum(r["outcome"] == "error" for r in rows),
        "attacked": sum(bool(r["attacked"]) for r in rows),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
    }


def _heartbeat(
    live: LiveRun,
    stop: threading.Event,
    tick: float = 0.25,
    limit: float = 2.0,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Notice when the whole process stops (the GIL held, or the OS pausing it). While it is
    stopped no claim moves, so the dashboard shows the load generator, not the pipeline."""
    last = clock()
    while not stop.wait(tick):
        now = clock()
        if now - last > limit:
            live.stalls.append((round(time.time() - (now - last), 1), round(now - last, 1)))
            live.log(f"traffic generator stalled for {now - last:.1f} s")
        last = now


def run_scenario(
    live: LiveRun,
    scenario: Sequence[Phase] = SCENARIO,
    workers: int = 5,
    seed: int = 0,
    annotate: Callable[[str], Any] | None = None,
    scale: float = 1.0,
    pace: tuple[float, float] = (0.2, 1.0),
) -> list[tuple[str, float, float]]:
    """8.6: start the workers, walk through the phases, stop. Returns [(phase, start, end)].

    `scale` shortens every phase (0.5 = half as long). The alert rules keep their `for:` times and
    rate windows, so a heavily shortened run shows the curves move but may end before alerts fire.
    """
    note = annotate or (lambda _text: None)
    stop = threading.Event()
    threads = [
        threading.Thread(target=live.traffic, args=(stop, seed + i, pace), daemon=True)
        for i in range(workers)
    ]
    threads.append(threading.Thread(target=_heartbeat, args=(live, stop), daemon=True))
    phase_log: list[tuple[str, float, float]] = []
    # The first phase is set before any worker starts, or each worker's first claim is "idle".
    if scenario:
        live.phase = scenario[0]
    for thread in threads:
        thread.start()
    try:
        for phase in scenario:
            t0 = time.time()  # before the annotation: its HTTP call is part of the phase
            live.phase = phase
            note(phase.name)
            time.sleep(max(0.0, t0 + phase.seconds * scale - time.time()))
            phase_log.append((phase.name, t0, time.time()))
            c = phase_counts(live.records, phase.name)
            live.log(
                f"{time.strftime('%H:%M:%S')}  {phase.name:<16} {c['claims']:>4} claims, "
                f"{c['correct']}/{c['claims']} handled correctly, {c['blocked']} blocked, "
                f"{c['errors']} pipeline errors, ${c['cost_usd']:.4f}"
            )
    finally:
        stop.set()
        live.phase = IDLE
        for thread in threads:
            thread.join(timeout=90)
        note("traffic stopped")
    return phase_log
