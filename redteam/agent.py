"""The red-team pipeline.

    PRD ──► lint (deterministic) ──► context extraction ──► persona reviews (parallel)
        ──► evidence verification (deterministic) ──► moderator (judge + dedupe)
        ──► verdict ──► launch gate (deterministic policy) ──► report
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Callable

from . import prompts as P
from .document import PRDDocument
from .lint import run_lint
from .llm import LLM
from .personas import Persona, select_personas
from .schemas import (
    SEVERITY_ORDER,
    DimensionScore,
    ModeratorOutput,
    PersonaReview,
    PRDContext,
    RedTeamReport,
    ReportFinding,
    VerdictOutput,
)

ProgressFn = Callable[[str], None]


@dataclass
class RedTeamConfig:
    personas: list[str] | None = None          # restrict to these persona keys
    extra_personas: list[Persona] = field(default_factory=list)
    max_findings_per_persona: int = 8
    concurrency: int = 4
    min_confidence: float = 0.4                # drop low-confidence findings before moderation
    drop_unverified_quotes: bool = False       # if True, unverifiable quotes are dropped outright
    use_moderator: bool = True


class LaunchGate:
    """Deterministic policy on top of the LLM's verdict. The model can be persuaded; the gate cannot."""

    @staticmethod
    def apply(report: RedTeamReport) -> None:
        if report.verdict is None:
            return
        c = report.counts()
        d = report.verdict.decision
        if c["blocker"] and d != "NO_GO":
            report.gate_override = f"Gate forced NO_GO: {c['blocker']} blocker(s) open (model said {d})."
            report.verdict.decision = "NO_GO"
        elif c["high"] and d == "GO":
            report.gate_override = f"Gate forced GO_WITH_CONDITIONS: {c['high']} high-severity finding(s) open (model said GO)."
            report.verdict.decision = "GO_WITH_CONDITIONS"


class RedTeamAgent:
    def __init__(self, llm: LLM | None, config: RedTeamConfig | None = None, progress: ProgressFn | None = None):
        self.llm = llm
        self.cfg = config or RedTeamConfig()
        self.progress = progress or (lambda msg: None)

    # ------------------------------------------------------------ public
    async def run(self, doc: PRDDocument) -> RedTeamReport:
        t0 = time.perf_counter()
        report = RedTeamReport(prd_title=doc.title, prd_path=doc.path, model=getattr(self.llm, "model", "offline"))

        self.progress("Running hygiene checks")
        report.lint_findings = run_lint(doc)

        if self.llm is None:
            report.verdict = self._offline_verdict(report)
            report.stats = {"mode": "offline", "seconds": round(time.perf_counter() - t0, 2)}
            return report

        self.progress("Understanding the product")
        report.context = await self._extract_context(doc)

        personas = select_personas(report.context, self.cfg.personas, self.cfg.extra_personas)
        report.personas_run = [p.name for p in personas]
        self.progress(f"Convening {len(personas)} reviewers: " + ", ".join(p.name.split(" (")[0] for p in personas))

        raw, failures = await self._run_personas(doc, report, personas)
        report.stats["persona_failures"] = len(failures)
        if failures:
            report.stats["failed_personas"] = ", ".join(failures)

        self.progress("Verifying quoted evidence against the PRD")
        candidates = self._verify(doc, raw)
        report.stats["raw_findings"] = len(raw)

        if self.cfg.use_moderator and candidates:
            self.progress(f"Moderating {len(candidates)} findings (judge + dedupe)")
            candidates = await self._moderate(doc, candidates)

        report.findings = self._finalise(candidates)
        report.stats["final_findings"] = len(report.findings)

        self.progress("Making the launch call")
        report.verdict = await self._verdict(report)
        LaunchGate.apply(report)

        report.stats.update(
            {
                "seconds": round(time.perf_counter() - t0, 1),
                "llm_calls": self.llm.usage.get("calls", 0),
                "input_tokens": self.llm.usage.get("input_tokens", 0),
                "output_tokens": self.llm.usage.get("output_tokens", 0),
                "prompt_version": P.PROMPT_VERSION,
            }
        )
        return report

    # ------------------------------------------------------------ stages
    async def _extract_context(self, doc: PRDDocument) -> PRDContext:
        return await self.llm.structured(
            system=P.CONTEXT_SYSTEM,
            user=f'<prd title="{doc.title}">\n{doc.text}\n</prd>',
            schema=PRDContext,
            tool_name="product_context",
            max_tokens=2000,
        )

    async def _run_personas(
        self, doc: PRDDocument, report: RedTeamReport, personas: list[Persona]
    ) -> tuple[list[tuple[Persona, ReportFinding]], list[str]]:
        sem = asyncio.Semaphore(self.cfg.concurrency)
        ctx_json = report.context.model_dump_json(indent=2) if report.context else "{}"
        lint_summary = "\n".join(f"- {f.title}" for f in report.lint_findings) or "(nothing)"
        user = P.PERSONA_USER.format(context=ctx_json, lint=lint_summary, title=doc.title, prd=doc.numbered())

        async def one(p: Persona) -> tuple[Persona, PersonaReview | Exception]:
            system = (
                p.system_prompt_block()
                + "\n\n"
                + P.PERSONA_RULES.format(max_findings=self.cfg.max_findings_per_persona, untrusted=P.UNTRUSTED_NOTE)
            )
            if p.key == "compliance_legal" and report.context and report.context.likely_regulations:
                system += "\n\nRegulations flagged as possibly relevant (verify, do not assume): " + ", ".join(
                    report.context.likely_regulations
                )
            async with sem:
                try:
                    review = await self.llm.structured(
                        system=system, user=user, schema=PersonaReview, tool_name="red_team_review", max_tokens=8000
                    )
                    self.progress(f"  {p.name}: {len(review.findings)} findings")
                    return p, review
                except Exception as e:  # one bad reviewer should not sink the review
                    self.progress(f"  {p.name}: FAILED ({e.__class__.__name__}: {e})")
                    return p, e

        results = await asyncio.gather(*(one(p) for p in personas))
        out: list[tuple[Persona, ReportFinding]] = []
        failures: list[str] = []
        for p, res in results:
            if isinstance(res, Exception):
                failures.append(p.name)
                continue
            report.persona_takes[p.name] = res.overall_take
            report.persona_signoffs[p.name] = res.would_sign_off
            for f in res.findings[: self.cfg.max_findings_per_persona]:
                out.append((p, ReportFinding(id="", personas=[p.name], **f.model_dump())))
        return out, failures

    def _verify(self, doc: PRDDocument, raw: list[tuple[Persona, ReportFinding]]) -> list[ReportFinding]:
        kept: list[ReportFinding] = []
        for _, f in raw:
            if f.confidence < self.cfg.min_confidence:
                continue
            if f.evidence.strip():
                ok, line = doc.locate(f.evidence)
                f.evidence_verified, f.line = ok, line
                if ok and line:  # trust the document over the model for where the quote lives
                    f.section = doc.section_for_line(line) or f.section
                if not ok and self.cfg.drop_unverified_quotes:
                    continue
            else:
                f.evidence_verified = None
            kept.append(f)
        return kept

    async def _moderate(self, doc: PRDDocument, findings: list[ReportFinding]) -> list[ReportFinding]:
        rows = []
        for i, f in enumerate(findings):
            quote = "(omission)" if f.evidence_verified is None else f'"{f.evidence}"' + (
                "" if f.evidence_verified else "  [QUOTE_NOT_FOUND in PRD]"
            )
            rows.append(
                f"[{i}] {f.personas[0]} | {f.severity.upper()} | {f.title}\n"
                f"    section: {f.section}\n    evidence: {quote}\n    issue: {f.issue}"
            )
        try:
            mod = await self.llm.structured(
                system=P.MODERATOR_SYSTEM,
                user=P.MODERATOR_USER.format(
                    title=doc.title, prd=doc.text, findings="\n".join(rows), last_index=len(findings) - 1
                ),
                schema=ModeratorOutput,
                tool_name="moderation",
                max_tokens=8000,
            )
        except Exception as e:
            self.progress(f"  Moderator failed ({e}); keeping unmoderated findings")
            return findings
        return apply_moderation(findings, mod)

    async def _verdict(self, report: RedTeamReport) -> VerdictOutput:
        dims = list(P.SCORECARD_DIMENSIONS)
        if report.context and report.context.uses_ai_ml:
            dims.insert(6, P.AI_DIMENSION)
        findings = "\n".join(
            f"{f.id} | {f.severity.upper()} | {', '.join(f.personas)} | {f.title} :: {f.issue}" for f in report.findings
        ) or "(no findings)"
        signoffs = "\n".join(
            f"- {name}: {'SIGNS OFF' if report.persona_signoffs.get(name) else 'WILL NOT SIGN'}. {take}"
            for name, take in report.persona_takes.items()
        )
        lint = f"{len(report.lint_findings)} hygiene issues: " + "; ".join(f.title for f in report.lint_findings[:15])
        return await self.llm.structured(
            system=P.VERDICT_SYSTEM,
            user=P.VERDICT_USER.format(
                context=report.context.model_dump_json(indent=2) if report.context else "{}",
                signoffs=signoffs or "(none)",
                findings=findings,
                lint=lint,
                dimensions=", ".join(dims),
            ),
            schema=VerdictOutput,
            tool_name="launch_verdict",
            max_tokens=4000,
        )

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _finalise(findings: list[ReportFinding]) -> list[ReportFinding]:
        findings = sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], -f.confidence, f.title))
        for i, f in enumerate(findings, 1):
            f.id = f"F-{i:03d}"
        return findings

    @staticmethod
    def _offline_verdict(report: RedTeamReport) -> VerdictOutput:
        sev = [f.severity for f in report.lint_findings]
        decision = "NO_GO" if sev.count("high") >= 3 else "GO_WITH_CONDITIONS" if sev else "GO"
        return VerdictOutput(
            decision=decision,
            executive_summary=(
                "Offline mode: only deterministic hygiene checks were run, no expert personas. "
                f"Found {len(sev)} hygiene issues ({sev.count('high')} high). Run with an API key for the full red-team review."
            ),
            launch_conditions=[f"Resolve: {f.title}" for f in report.lint_findings if f.severity == "high"],
            scorecard=[DimensionScore(dimension="Clarity & completeness", score=max(1, 5 - sev.count("high") - sev.count("medium") // 2), note="Based on hygiene checks only.")],
            top_risk_ids=[f.id for f in report.lint_findings if f.severity == "high"][:5],
        )


def apply_moderation(findings: list[ReportFinding], mod: ModeratorOutput) -> list[ReportFinding]:
    """Apply keep/drop + severity changes, then merge duplicate groups. Pure function, easy to test."""
    decisions = {d.index: d for d in mod.decisions if 0 <= d.index < len(findings)}
    alive: dict[int, ReportFinding] = {}
    for i, f in enumerate(findings):
        d = decisions.get(i)
        if d is None:  # moderator skipped it: keep as-is rather than silently lose it
            alive[i] = f
            continue
        if not d.keep:
            continue
        if d.adjusted_severity != f.severity:
            f.moderator_note = f"Severity {f.severity} -> {d.adjusted_severity}: {d.reason}"
            f.severity = d.adjusted_severity
        alive[i] = f

    merged_away: set[int] = set()
    for group in mod.duplicate_groups:
        members = [i for i in dict.fromkeys(group) if i in alive and i not in merged_away]
        if len(members) < 2:
            continue
        members.sort(key=lambda i: (SEVERITY_ORDER[alive[i].severity], -alive[i].confidence))
        primary = alive[members[0]]
        for i in members[1:]:
            for p in alive[i].personas:
                if p not in primary.personas:
                    primary.personas.append(p)
            primary.confidence = max(primary.confidence, alive[i].confidence)
            merged_away.add(i)
    return [f for i, f in alive.items() if i not in merged_away]


def run_sync(agent: RedTeamAgent, doc: PRDDocument) -> RedTeamReport:
    return asyncio.run(agent.run(doc))


def report_to_json(report: RedTeamReport) -> str:
    return json.dumps(report.model_dump(), indent=2, ensure_ascii=False)
