"""Offline tests. No API key needed: the LLM is replaced by ScriptedLLM."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from redteam import LaunchGate, RedTeamAgent, RedTeamConfig, ScriptedLLM, apply_moderation, load_prd
from redteam.llm import _inline_refs
from redteam.lint import run_lint
from redteam.report import to_html, to_json, to_markdown
from redteam.schemas import ModeratorOutput, PersonaReview, RedTeamReport, ReportFinding, VerdictOutput

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_prd.md"


@pytest.fixture(scope="module")
def doc():
    return load_prd(SAMPLE)


def _finding(**kw):
    base = dict(
        title="t", severity="medium", category="c", section="s", evidence="", issue="i",
        failure_scenario="f", recommendation="r", question_for_pm="q", confidence=0.8,
    )
    return {**base, **kw}


# ---------------------------------------------------------------- document
def test_sections_and_title(doc):
    assert doc.title.startswith("RefillRx")
    titles = doc.section_titles()
    assert "6. Data" in titles and "10. Launch plan" in titles


def test_locate_exact_and_fuzzy(doc):
    ok, line = doc.locate("stored in our S3 bucket indefinitely so we can use them for model improvement")
    assert ok and doc.lines[line - 1].startswith("All prescription images")
    # Different case, curly quotes, extra spaces, a small word change
    ok, _ = doc.locate("users SHARE their  Aadhaar number on whatsapp at onboarding. We keep it in the user profile")
    assert ok
    ok, _ = doc.locate("All data is encrypted with customer-managed keys and deleted after 30 days")
    assert not ok


# ---------------------------------------------------------------- lint
def test_lint_catches_planted_hygiene_issues(doc):
    titles = " | ".join(f.title for f in run_lint(doc))
    assert "Rollback" in titles
    assert "TBD" in titles
    assert "Success metrics have no numbers" in titles
    assert "real-time" in titles.lower()


# ---------------------------------------------------------------- schema plumbing
def test_tool_schema_has_no_refs():
    s = json.dumps(_inline_refs(PersonaReview.model_json_schema()))
    assert "$ref" not in s and "$defs" not in s


# ---------------------------------------------------------------- moderation
def test_apply_moderation_drop_adjust_merge():
    fs = [ReportFinding(id="", personas=[p], **_finding(title=p, severity=s, confidence=c))
          for p, s, c in [("A", "high", 0.7), ("B", "blocker", 0.9), ("C", "low", 0.5), ("D", "medium", 0.6)]]
    mod = ModeratorOutput.model_validate({
        "decisions": [
            {"index": 0, "keep": True, "adjusted_severity": "high", "reason": "ok"},
            {"index": 1, "keep": True, "adjusted_severity": "blocker", "reason": "ok"},
            {"index": 2, "keep": False, "adjusted_severity": "low", "reason": "generic"},
            {"index": 3, "keep": True, "adjusted_severity": "high", "reason": "under-called"},
        ],
        "duplicate_groups": [[0, 1]],
    })
    out = apply_moderation(fs, mod)
    names = {f.title: f for f in out}
    assert set(names) == {"B", "D"}                     # C dropped, A merged into B
    assert names["B"].personas == ["B", "A"]
    assert names["D"].severity == "high" and "medium -> high" in names["D"].moderator_note


# ---------------------------------------------------------------- gate
def test_gate_overrides_optimistic_model():
    r = RedTeamReport(prd_title="x", findings=[ReportFinding(id="F-001", personas=["p"], **_finding(severity="blocker"))])
    r.verdict = VerdictOutput(decision="GO", executive_summary="", launch_conditions=[], scorecard=[], top_risk_ids=[])
    LaunchGate.apply(r)
    assert r.verdict.decision == "NO_GO" and "blocker" in r.gate_override


# ---------------------------------------------------------------- full pipeline
def _scripted(fail_persona: str | None = None) -> ScriptedLLM:
    def context(_s, _u):
        return dict(
            product_name="RefillRx", one_line_summary="WhatsApp refills", domain="consumer health",
            target_users=["chronic patients"], data_handled=["prescriptions"], handles_sensitive_data=True,
            geographies=["India"], third_party_dependencies=["LLM API"], uses_ai_ml=True, involves_payments=True,
            launch_scope="big-bang", likely_regulations=["India DPDP Act 2023"],
        )

    def review(system, _u):
        if fail_persona and fail_persona in system:
            raise RuntimeError("simulated outage")
        if "Data Protection Officer" in system:
            return dict(overall_take="No.", would_sign_off=False, findings=[
                _finding(title="Indefinite retention of health data", severity="blocker",
                         evidence="stored in our S3 bucket indefinitely so we can use them for model improvement"),
                _finding(title="Invented quote", severity="high", evidence="data is deleted every night at midnight"),
            ])
        if "Security" in system:
            return dict(overall_take="Phone number is not identity.", would_sign_off=False, findings=[
                _finding(title="Phone-number-only identity", severity="high",
                         evidence="Any message from that number is treated as the account holder."),
                _finding(title="Low confidence musing", severity="low", confidence=0.1),
            ])
        return dict(overall_take="Fine from here.", would_sign_off=True, findings=[])

    def moderation(_s, user):
        rows = [line for line in user.splitlines() if line.startswith("[")]
        decisions = [{"index": i, "keep": True, "adjusted_severity": row.split(" | ")[1].lower(), "reason": "ok"}
                     for i, row in enumerate(rows)]
        return {"decisions": decisions, "duplicate_groups": []}

    def verdict(_s, user):
        return dict(decision="GO_WITH_CONDITIONS", executive_summary="Optimistic model.", launch_conditions=["Fix retention"],
                    scorecard=[{"dimension": "Security", "score": 2, "note": "weak"}], top_risk_ids=["F-001"])

    return ScriptedLLM({"product_context": context, "red_team_review": review, "moderation": moderation, "launch_verdict": verdict})


def test_pipeline_end_to_end(doc):
    llm = _scripted()
    report = asyncio.run(RedTeamAgent(llm, RedTeamConfig(min_confidence=0.4)).run(doc))

    # All 9 personas run because the context says the product uses AI
    assert len(report.personas_run) == 9
    titles = [f.title for f in report.findings]
    assert "Low confidence musing" not in titles                       # confidence filter
    retention = next(f for f in report.findings if f.title.startswith("Indefinite"))
    assert retention.evidence_verified is True and retention.line and retention.section == "6. Data"
    invented = next(f for f in report.findings if f.title == "Invented quote")
    assert invented.evidence_verified is False                         # flagged, not silently trusted
    assert [f.id for f in report.findings][0] == "F-001" and report.findings[0].severity == "blocker"
    # Model said GO_WITH_CONDITIONS but a blocker is open -> deterministic gate forces NO_GO
    assert report.verdict.decision == "NO_GO" and report.gate_override
    assert report.persona_signoffs["Ananya (Data Protection Officer)"] is False


def test_pipeline_survives_a_failed_persona(doc):
    report = asyncio.run(RedTeamAgent(_scripted(fail_persona="Security"), RedTeamConfig()).run(doc))
    assert report.stats["persona_failures"] == 1
    assert any(f.title.startswith("Indefinite") for f in report.findings)


def test_strict_evidence_drops_invented_quotes(doc):
    report = asyncio.run(RedTeamAgent(_scripted(), RedTeamConfig(drop_unverified_quotes=True)).run(doc))
    assert all(f.title != "Invented quote" for f in report.findings)


def test_persona_subset(doc):
    llm = _scripted()
    report = asyncio.run(RedTeamAgent(llm, RedTeamConfig(personas=["security", "privacy"])).run(doc))
    assert len(report.personas_run) == 2


def test_offline_mode_and_renderers(doc):
    report = asyncio.run(RedTeamAgent(None).run(doc))
    assert report.verdict and report.lint_findings and not report.findings
    full = asyncio.run(RedTeamAgent(_scripted()).run(doc))
    for r in (report, full):
        assert "Verdict" in to_markdown(r)
        assert to_html(r).startswith("<!DOCTYPE html>")
        json.loads(to_json(r))


def test_lint_ignores_terms_that_are_quoted():
    from redteam import PRDDocument
    d = PRDDocument(text='# P\n\n## Goals\n\nAvoid words like "fast" and `TBD` in requirements.\n\nThe API must be fast.\n')
    vague = [f for f in run_lint(d) if f.title.startswith("Vague")]
    assert [f.title for f in vague] == ["Vague language: 'fast' (1x)"] and vague[0].line == 7
