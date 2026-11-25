"""Seeded-defect benchmark: does the red team catch what we planted, without drowning the PM in noise?

    python evals/run_eval.py                         # full agent, 1 run
    python evals/run_eval.py --runs 3                # mean and run-to-run spread
    python evals/run_eval.py --baseline              # single "find all risks" prompt, same pipeline
    python evals/run_eval.py --no-moderator          # ablation: critics without the judge
    python evals/run_eval.py --personas security,privacy

Each run appends one row to evals/RESULTS.md, so experiments accumulate into a comparison table.

Metrics
  recall                share of planted defects caught by at least one finding
  blocker_recall        recall on blocker-level defects only (north-star metric)
  severity_match        caught defects where the agent's severity is within one level of ground truth
  precision             share of agent findings the judge rates as valid (correct about the PRD, specific, actionable)
  unverified_quote_rate share of quoted findings whose quote is NOT in the PRD (deterministic, no judge)
  verdict               the agent's launch call (expected NO_GO for the sample)
  tokens / seconds      cost and latency per review
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from redteam import AnthropicLLM, Persona, RedTeamAgent, RedTeamConfig, load_prd  # noqa: E402
from redteam.llm import DEFAULT_MODEL, LLM  # noqa: E402
from redteam.schemas import SEVERITY_ORDER  # noqa: E402

# A deliberately simple baseline: one reviewer, one prompt, same budget, same moderator and gate.
# If the multi-persona panel cannot beat this, the panel is not worth its cost.
GENERALIST = Persona(
    key="generalist",
    name="Generalist reviewer",
    title="an experienced reviewer of product requirement documents",
    mandate="Find every risk in this PRD that should be addressed before launch, across any area.",
    focus_areas=["Anything that could go wrong"],
    red_flags=["Anything serious"],
)


class DefectMatch(BaseModel):
    defect_id: str
    caught: bool = Field(description="True only if a finding identifies the same underlying problem, not merely the same topic.")
    matched_finding_ids: list[str]
    reason: str


class JudgeOutput(BaseModel):
    matches: list[DefectMatch]
    invalid_finding_ids: list[str] = Field(
        description="IDs of agent findings that are factually wrong about the PRD, generic advice not specific to this product, "
        "or not actionable. Findings that are valid but not in the planted list are NOT invalid."
    )


JUDGE_SYSTEM = """You grade a PRD red-team agent against a list of planted defects.
1. For each planted defect, decide whether any agent finding identifies the SAME underlying problem.
   Topic overlap is not enough: the finding must point at the actual flaw. One finding may catch several defects.
2. Separately, list agent findings that are invalid: factually wrong about the PRD, generic, or not actionable.
   A valid finding that simply is not on the planted list is fine and must not be marked invalid.
Be strict but fair."""


async def one_run(
    defects: list[dict], prd_path: Path, llm: LLM, personas: list[str] | None, baseline: bool, moderator: bool
) -> dict:
    cfg = RedTeamConfig(personas=personas, use_moderator=moderator)
    if baseline:
        cfg = RedTeamConfig(personas=["generalist"], extra_personas=[GENERALIST], max_findings_per_persona=40, use_moderator=moderator)
    doc = load_prd(prd_path)
    report = await RedTeamAgent(llm, cfg, progress=lambda m: print("  ", m)).run(doc)

    findings = report.findings + report.lint_findings
    listing = "\n".join(f"{f.id} [{f.severity}] {f.title}: {f.issue}" for f in findings)
    defect_list = "\n".join(f"{d['id']}: {d['defect']}" for d in defects)
    judged = await llm.structured(
        system=JUDGE_SYSTEM,
        user=(f'<prd>\n{doc.text}\n</prd>\n\n<planted_defects>\n{defect_list}\n</planted_defects>\n\n'
              f"<agent_findings>\n{listing}\n</agent_findings>"),
        schema=JudgeOutput,
        tool_name="grade",
        max_tokens=4000,
    )
    by_id = {f.id: f for f in findings}
    rows = []
    for d in defects:
        m = next((x for x in judged.matches if x.defect_id == d["id"]), None)
        caught = bool(m and m.caught)
        sev_ok = None
        if caught:
            sevs = [SEVERITY_ORDER[by_id[i].severity] for i in m.matched_finding_ids if i in by_id]
            sev_ok = bool(sevs) and min(abs(s - SEVERITY_ORDER[d["severity"]]) for s in sevs) <= 1
        rows.append({**d, "caught": caught, "matched": m.matched_finding_ids if m else [], "severity_ok": sev_ok})

    llm_ids = {f.id for f in report.findings}
    invalid = [i for i in judged.invalid_finding_ids if i in llm_ids]
    quoted = [f for f in report.findings if f.evidence_verified is not None]
    return {
        "rows": rows,
        "verdict": report.verdict.decision,
        "n_findings": len(report.findings),
        "n_invalid": len(invalid),
        "n_quoted": len(quoted),
        "n_unverified": sum(1 for f in quoted if f.evidence_verified is False),
        "stats": report.stats,
    }


def summarise(run: dict) -> dict:
    rows = run["rows"]
    caught = [r for r in rows if r["caught"]]
    blockers = [r for r in rows if r["severity"] == "blocker"]
    lanes: dict[str, list[bool]] = {}
    for r in rows:
        lanes.setdefault(r["lane"], []).append(r["caught"])
    return {
        "recall": len(caught) / len(rows),
        "blocker_recall": sum(r["caught"] for r in blockers) / max(1, len(blockers)),
        "severity_match": sum(bool(r["severity_ok"]) for r in caught) / max(1, len(caught)),
        "precision": 1 - run["n_invalid"] / max(1, run["n_findings"]),
        "unverified_quote_rate": run["n_unverified"] / max(1, run["n_quoted"]),
        "lane_recall": {k: sum(v) / len(v) for k, v in lanes.items()},
        "missed": [r["id"] + " " + r["defect"] for r in rows if not r["caught"]],
        "verdict": run["verdict"],
        "n_findings": run["n_findings"],
        "tokens": int(run["stats"].get("input_tokens", 0)) + int(run["stats"].get("output_tokens", 0)),
        "seconds": float(run["stats"].get("seconds", 0)),
    }


def _fmt(values: list[float], pct: bool = True) -> str:
    m = statistics.mean(values)
    s = f"{m:.0%}" if pct else f"{m:,.0f}"
    if len(values) > 1:
        sd = statistics.stdev(values)
        s += f" ± {sd:.0%}" if pct else f" ± {sd:,.0f}"
    return s


def results_row(label: str, model: str, summaries: list[dict]) -> str:
    g = lambda k: [s[k] for s in summaries]  # noqa: E731
    verdicts = ", ".join(sorted(set(g("verdict"))))
    return (f"| {date.today()} | {label} | {model} | {len(summaries)} | {_fmt(g('blocker_recall'))} | {_fmt(g('recall'))} | "
            f"{_fmt(g('precision'))} | {_fmt(g('severity_match'))} | {_fmt(g('unverified_quote_rate'))} | "
            f"{_fmt(g('n_findings'), False)} | {_fmt(g('tokens'), False)} | {_fmt(g('seconds'), False)}s | {verdicts} |")


RESULTS_HEADER = """# Eval results

Generated by `python evals/run_eval.py`. One row per experiment. Benchmark: `examples/sample_prd.md` with 15 planted defects (4 blockers).

| Date | Config | Model | Runs | Blocker recall | Recall | Precision | Severity match | Unverified quotes | Findings | Tokens | Time | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
"""


def append_results(path: Path, row: str) -> None:
    if not path.exists():
        path.write_text(RESULTS_HEADER, encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(row + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--defects", default=str(ROOT / "evals" / "planted_defects.json"))
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--personas")
    ap.add_argument("--baseline", action="store_true", help="Single generalist reviewer instead of the panel")
    ap.add_argument("--no-moderator", action="store_true", help="Ablation: skip the judge/dedupe pass")
    ap.add_argument("--out", default=str(ROOT / "evals" / "results.json"))
    ap.add_argument("--table", default=str(ROOT / "evals" / "RESULTS.md"))
    args = ap.parse_args()

    spec = json.loads(Path(args.defects).read_text())
    prd_path = ROOT / spec["prd"]
    personas = args.personas.split(",") if args.personas else None
    label = "baseline: single prompt" if args.baseline else (f"panel: {args.personas}" if personas else "panel: all")
    if args.no_moderator:
        label += ", no moderator"

    summaries = []
    for i in range(args.runs):
        print(f"Run {i + 1}/{args.runs}  [{label}]")
        llm = AnthropicLLM(model=args.model)
        run = asyncio.run(one_run(spec["defects"], prd_path, llm, personas, args.baseline, not args.no_moderator))
        summaries.append(summarise(run))

    g = lambda k: [s[k] for s in summaries]  # noqa: E731
    print(f"\n=== {label} · {args.model} · {args.runs} run(s) ===")
    print(f"blocker recall:        {_fmt(g('blocker_recall'))}")
    print(f"recall:                {_fmt(g('recall'))}")
    print(f"precision:             {_fmt(g('precision'))}")
    print(f"severity match:        {_fmt(g('severity_match'))}")
    print(f"unverified quotes:     {_fmt(g('unverified_quote_rate'))}")
    print(f"verdicts:              {g('verdict')}  (expected NO_GO)")
    print("lane recall (last):    " + ", ".join(f"{k} {v:.0%}" for k, v in summaries[-1]["lane_recall"].items()))
    for m in summaries[-1]["missed"]:
        print("  missed:", m)

    Path(args.out).write_text(json.dumps({"label": label, "model": args.model, "runs": summaries}, indent=2))
    append_results(Path(args.table), results_row(label, args.model, summaries))
    print(f"\nwrote {args.out} and appended a row to {args.table}")


if __name__ == "__main__":
    main()
