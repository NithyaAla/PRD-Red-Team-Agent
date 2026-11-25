"""Command line entry point.

    redteam review examples/sample_prd.md
    redteam review my_prd.docx --personas security,privacy --format md,html
    redteam review my_prd.md --offline
    redteam personas
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .agent import RedTeamAgent, RedTeamConfig
from .document import load_prd
from .llm import DEFAULT_MODEL, AnthropicLLM
from .personas import DEFAULT_PERSONAS, load_custom_personas
from .report import DECISION_LABEL, GO_NOTE, to_html, to_json, to_markdown

console = Console()


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def cmd_personas(_: argparse.Namespace) -> int:
    t = Table(title="Red-team personas")
    t.add_column("key", style="bold")
    t.add_column("name")
    t.add_column("mandate")
    for p in DEFAULT_PERSONAS:
        t.add_row(p.key, p.name, p.mandate)
    console.print(t)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    _load_dotenv()
    doc = load_prd(args.prd)
    extra = load_custom_personas(args.persona_file) if args.persona_file else []
    cfg = RedTeamConfig(
        personas=[p.strip() for p in args.personas.split(",")] if args.personas else None,
        extra_personas=extra,
        max_findings_per_persona=args.max_findings,
        concurrency=args.concurrency,
        min_confidence=args.min_confidence,
        drop_unverified_quotes=args.strict_evidence,
        use_moderator=not args.no_moderator,
    )
    llm = None if args.offline else AnthropicLLM(model=args.model)
    agent = RedTeamAgent(llm, cfg, progress=lambda m: console.print(f"[dim]›[/dim] {m}"))

    console.rule(f"[bold]Red-teaming[/bold] {doc.title}")
    report = asyncio.run(agent.run(doc))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.prd).stem + "_redteam"
    written = []
    for fmt in [f.strip() for f in args.format.split(",")]:
        path = out_dir / f"{stem}.{fmt}"
        content = {"md": to_markdown, "html": to_html, "json": to_json}[fmt](report)
        path.write_text(content, encoding="utf-8")
        written.append(path)

    v = report.verdict
    colour = {"GO": "green", "GO_WITH_CONDITIONS": "yellow", "NO_GO": "red"}[v.decision]
    c = report.counts()
    console.rule()
    console.print(f"[bold {colour}]VERDICT: {DECISION_LABEL[v.decision]}[/]")
    if report.gate_override:
        console.print(f"[red]{report.gate_override}[/red]")
    if v.decision == "GO":
        console.print(f"[dim]{GO_NOTE}[/dim]")
    console.print(
        f"{c['blocker']} blocker · {c['high']} high · {c['medium']} medium · {c['low']} low · {len(report.lint_findings)} hygiene"
    )
    for p in written:
        console.print(f"[green]wrote[/green] {p}")
    # Non-zero exit on NO_GO so this can gate a CI pipeline / docs-as-code PR.
    return 2 if (args.fail_on_nogo and v.decision == "NO_GO") else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="redteam", description="Tear down a PRD before launch.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("review", help="Red-team a PRD file (.md, .txt, .pdf, .docx)")
    r.add_argument("prd")
    r.add_argument("--out", default="reports")
    r.add_argument("--format", default="md,html,json", help="Comma list of md, html, json")
    r.add_argument("--model", default=DEFAULT_MODEL)
    r.add_argument("--personas", help="Comma list of persona keys to run (default: all applicable)")
    r.add_argument("--persona-file", help="JSON file with extra custom personas")
    r.add_argument("--max-findings", type=int, default=8, help="Max findings per persona")
    r.add_argument("--concurrency", type=int, default=4)
    r.add_argument("--min-confidence", type=float, default=0.4)
    r.add_argument("--strict-evidence", action="store_true", help="Drop findings whose quote is not found in the PRD")
    r.add_argument("--no-moderator", action="store_true", help="Skip the judge/dedupe pass (cheaper, noisier)")
    r.add_argument("--offline", action="store_true", help="Hygiene checks only, no LLM calls")
    r.add_argument("--fail-on-nogo", action="store_true", help="Exit code 2 when the verdict is NO-GO")
    r.set_defaults(func=cmd_review)

    p = sub.add_parser("personas", help="List built-in personas")
    p.set_defaults(func=cmd_personas)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        console.print(f"[red]error:[/red] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
