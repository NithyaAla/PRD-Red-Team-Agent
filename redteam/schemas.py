"""Typed contracts for every stage of the red-team pipeline.

The LLM is forced to answer through these schemas (via tool use), so every
finding is structured, comparable across personas, and machine-checkable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["blocker", "high", "medium", "low"]
SEVERITY_ORDER: dict[str, int] = {"blocker": 0, "high": 1, "medium": 2, "low": 3}

Decision = Literal["GO", "GO_WITH_CONDITIONS", "NO_GO"]


# ---------------------------------------------------------------- stage 1
class PRDContext(BaseModel):
    """What the agent understands about the product before attacking it."""

    product_name: str
    one_line_summary: str
    domain: str = Field(description="Industry / domain, e.g. 'consumer health', 'B2B fintech'.")
    target_users: list[str]
    data_handled: list[str] = Field(description="Kinds of data the product collects, stores or processes.")
    handles_sensitive_data: bool = Field(
        description="True if health, financial, biometric, government ID, children's, precise location or similar data is involved."
    )
    geographies: list[str] = Field(description="Countries / regions where it launches or where users live.")
    third_party_dependencies: list[str]
    uses_ai_ml: bool = Field(description="True if any model, LLM, OCR, recommender or automated decisioning is involved.")
    involves_payments: bool
    launch_scope: str = Field(description="How and to whom it launches: beta, % rollout, big-bang, etc.")
    likely_regulations: list[str] = Field(
        description="Laws, regulations or standards that plausibly apply, e.g. 'India DPDP Act 2023', 'GDPR', 'HIPAA', 'PCI DSS', 'WCAG 2.2'."
    )


# ---------------------------------------------------------------- stage 2
class Finding(BaseModel):
    """One attack on the PRD, as produced by a persona."""

    title: str = Field(description="Short, specific headline (max ~12 words).")
    severity: Severity
    category: str = Field(description="Sub-area within the persona's lane, e.g. 'data retention', 'rollback'.")
    section: str = Field(description="PRD section heading this relates to, or 'MISSING' if the PRD omits it entirely.")
    evidence: str = Field(
        description="VERBATIM quote (5-40 words) copied from the PRD that shows the problem. Empty string only if the problem is an omission."
    )
    issue: str = Field(description="What is wrong or missing, in 1-3 sentences.")
    failure_scenario: str = Field(description="Concrete story of how this hurts users, the company, or the launch.")
    recommendation: str = Field(description="Specific fix the PM can put into the PRD.")
    question_for_pm: str = Field(description="The pointed question you would ask the PM in the review meeting.")
    confidence: float = Field(ge=0.0, le=1.0)


class PersonaReview(BaseModel):
    findings: list[Finding]
    overall_take: str = Field(description="Your blunt 2-3 sentence verdict on this PRD from your seat.")
    would_sign_off: bool = Field(description="Would you sign off on launch as written?")


# ---------------------------------------------------------------- stage 3
class ModeratorDecision(BaseModel):
    index: int
    keep: bool = Field(description="False if the finding is wrong, already addressed in the PRD, or pure generic advice.")
    adjusted_severity: Severity
    reason: str = Field(description="One sentence justifying keep/drop and any severity change.")


class ModeratorOutput(BaseModel):
    decisions: list[ModeratorDecision]
    duplicate_groups: list[list[int]] = Field(
        description="Groups of finding indices that describe the same underlying problem. Each group has 2+ indices."
    )


# ---------------------------------------------------------------- stage 4
class DimensionScore(BaseModel):
    dimension: str
    score: int = Field(ge=1, le=5, description="1 = not launch-ready, 5 = excellent.")
    note: str


class VerdictOutput(BaseModel):
    decision: Decision
    executive_summary: str = Field(description="4-6 sentences a VP could read in 30 seconds.")
    launch_conditions: list[str] = Field(description="Concrete conditions that must be true before launch.")
    scorecard: list[DimensionScore]
    top_risk_ids: list[str] = Field(description="IDs of the 3-5 findings that matter most, e.g. ['F-003', 'F-001'].")


# ---------------------------------------------------------------- output
class ReportFinding(Finding):
    id: str
    personas: list[str]
    evidence_verified: bool | None = Field(
        default=None, description="True if the quote was found in the PRD, False if not, None for omissions."
    )
    line: int | None = None
    source: Literal["llm", "lint"] = "llm"
    moderator_note: str = ""


class RedTeamReport(BaseModel):
    prd_title: str
    prd_path: str = ""
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    model: str = ""
    context: PRDContext | None = None
    personas_run: list[str] = []
    persona_takes: dict[str, str] = {}
    persona_signoffs: dict[str, bool] = {}
    findings: list[ReportFinding] = []
    lint_findings: list[ReportFinding] = []
    verdict: VerdictOutput | None = None
    gate_override: str = ""
    stats: dict[str, int | float | str] = {}

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in SEVERITY_ORDER}
        for f in self.findings:
            out[f.severity] += 1
        return out
