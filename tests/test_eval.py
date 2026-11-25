"""The eval harness itself is tested offline, so metric bugs can't hide behind API calls."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "tests"))

import run_eval  # noqa: E402
from test_redteam import _scripted  # noqa: E402

SPEC = json.loads((ROOT / "evals" / "planted_defects.json").read_text())


def _with_judge(llm):
    def grade(_s, user):
        ids = [line.split(" ")[0] for line in user.split("<agent_findings>")[1].splitlines() if line.startswith("F-")]
        matches = [{"defect_id": d["id"], "caught": d["id"] in ("D03", "D06"), "matched_finding_ids": ids[:1], "reason": "x"}
                   for d in SPEC["defects"]]
        return {"matches": matches, "invalid_finding_ids": [i for i in ids if i != ids[0]][:1]}

    llm.handlers["grade"] = grade
    return llm


def test_eval_metrics_offline():
    run = asyncio.run(run_eval.one_run(SPEC["defects"], ROOT / SPEC["prd"], _with_judge(_scripted()), None, False, True))
    s = run_eval.summarise(run)
    assert s["recall"] == 2 / 15
    assert s["blocker_recall"] == 1 / 4                      # D03 is a blocker, D06 is high
    assert 0 < s["precision"] < 1                             # one finding judged invalid
    assert s["unverified_quote_rate"] > 0                     # the scripted 'invented quote'
    assert s["verdict"] == "NO_GO"
    row = run_eval.results_row("panel: all", "scripted", [s, s])
    assert row.count("|") == 14 and "± 0%" in row


def test_baseline_runs_single_generalist():
    llm = _with_judge(_scripted())
    asyncio.run(run_eval.one_run(SPEC["defects"], ROOT / SPEC["prd"], llm, None, True, True))
    reviews = [c for c in llm.calls if c[0] == "red_team_review"]
    assert len(reviews) == 1 and "Generalist reviewer" in reviews[0][1]
