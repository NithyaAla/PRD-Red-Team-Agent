"""Deterministic PRD hygiene checks. Free, instant, and they work offline.

These catch the boring-but-costly gaps (no rollback plan, no metrics, 'TBD'
everywhere) so the LLM personas can spend their attention on deeper issues.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .document import PRDDocument
from .schemas import ReportFinding, Severity


@dataclass
class ExpectedSection:
    name: str
    keywords: tuple[str, ...]
    severity: Severity
    why: str


EXPECTED_SECTIONS: list[ExpectedSection] = [
    ExpectedSection("Problem / background", ("problem", "background", "context", "why", "opportunity"), "medium",
                    "Without a stated problem, reviewers cannot judge whether the solution fits."),
    ExpectedSection("Goals", ("goal", "objective"), "medium", "Goals anchor every scope trade-off."),
    ExpectedSection("Non-goals / out of scope", ("non-goal", "non goal", "out of scope", "not in scope", "scope"), "low",
                    "Missing non-goals invite scope creep and mismatched expectations."),
    ExpectedSection("Success metrics", ("metric", "kpi", "success", "measure"), "high",
                    "Nobody will be able to tell whether the launch worked."),
    ExpectedSection("Requirements / user stories", ("requirement", "user stor", "functional", "feature", "solution"), "high",
                    "Engineering has nothing concrete to build or test against."),
    ExpectedSection("Non-functional requirements", ("non-functional", "nfr", "performance", "latency", "reliability", "availability", "sla", "slo"), "medium",
                    "Performance and reliability expectations will be set by accident."),
    ExpectedSection("Security & privacy", ("security", "privacy", "data protection", "compliance", "consent"), "high",
                    "Data handling decisions will be made ad hoc by engineers."),
    ExpectedSection("Rollout / launch plan", ("rollout", "roll-out", "launch", "release", "go-to-market", "gtm"), "medium",
                    "No plan for who gets it first and how exposure ramps."),
    ExpectedSection("Rollback / kill switch", ("rollback", "roll back", "kill switch", "feature flag", "revert"), "high",
                    "If launch goes wrong there is no agreed way to undo it."),
    ExpectedSection("Monitoring / analytics", ("monitor", "alert", "observab", "analytics", "instrument", "dashboard"), "medium",
                    "Failures and adoption will be invisible after launch."),
    ExpectedSection("Dependencies", ("dependenc", "integration", "third party", "third-party", "vendor"), "medium",
                    "Cross-team and vendor risk is untracked."),
    ExpectedSection("Risks / open questions", ("risk", "open question", "assumption", "faq"), "low",
                    "Known unknowns are not written down, so nobody owns them."),
]

VAGUE_TERMS: dict[str, Severity] = {
    r"\bTBD\b": "medium", r"\bTBC\b": "medium", r"\bto be decided\b": "medium", r"\bwill be ready\b": "medium",
    r"\bfast\b": "low", r"\bquick(ly)?\b": "low", r"\bseamless(ly)?\b": "low", r"\bintuitive\b": "low",
    r"\buser[- ]friendly\b": "low", r"\bscalable\b": "low", r"\brobust\b": "low", r"\breal[- ]time\b": "low",
    r"\bhigh accuracy\b": "medium", r"\baccuracy should be high\b": "medium", r"\bas needed\b": "low",
    r"\betc\.?": "low", r"\bbest[- ]in[- ]class\b": "low", r"\bminimal\b": "low", r"\beasy\b": "low",
    r"\bsecure(ly)?\b": "low", r"\bshould\b": "low", r"\bnice to have\b": "low",
}

QUOTED = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d|`[^`\n]*`')

SENSITIVE_TERMS = [
    "aadhaar", "pan card", "passport", "ssn", "social security", "health", "medical", "diagnos", "prescription",
    "biometric", "fingerprint", "face", "location", "gps", "card number", "cvv", "bank account", "salary",
    "income", "child", "minor", "religion", "caste", "genetic",
]
AI_TERMS = ["llm", "gpt", "claude", "gemini", "machine learning", " ml ", "model", "ocr", "ai ", "ai-", "genai", "classifier", "recommendation engine"]
AI_SAFEGUARD_TERMS = ["eval", "accuracy threshold", "precision", "recall", "hallucinat", "human review", "human-in-the-loop", "fallback", "confidence"]


def _find_section(doc: PRDDocument, keywords: tuple[str, ...]) -> bool:
    titles = " | ".join(t.lower() for t in doc.section_titles())
    return any(k in titles for k in keywords)


def run_lint(doc: PRDDocument) -> list[ReportFinding]:
    findings: list[ReportFinding] = []
    lower = doc.text.lower()

    def add(**kw) -> None:
        findings.append(
            ReportFinding(
                id=f"L-{len(findings) + 1:03d}",
                personas=["PRD Linter"],
                source="lint",
                confidence=1.0,
                **kw,
            )
        )

    # 1. Missing standard sections
    for exp in EXPECTED_SECTIONS:
        if not _find_section(doc, exp.keywords):
            add(
                title=f"No '{exp.name}' section",
                severity=exp.severity,
                category="structure",
                section="MISSING",
                evidence="",
                evidence_verified=None,
                issue=f"The PRD has no section covering {exp.name.lower()}.",
                failure_scenario=exp.why,
                recommendation=f"Add a '{exp.name}' section.",
                question_for_pm=f"Where is the {exp.name.lower()} for this launch?",
            )

    # 2. Vague / weasel language, grouped per term. Words inside quotes or backticks are being
    #    mentioned, not used ("avoid words like 'fast'"), so they are ignored.
    unquoted = [QUOTED.sub(" ", l) for l in doc.lines]
    for pattern, sev in VAGUE_TERMS.items():
        rx = re.compile(pattern, re.IGNORECASE)
        hits = [(i, doc.lines[i - 1].strip()) for i, l in enumerate(unquoted, 1) if rx.search(l) and not l.lstrip().startswith("#")]
        if not hits:
            continue
        term = rx.search(unquoted[hits[0][0] - 1]).group(0)
        if sev == "low" and len(hits) < 2 and term.lower() in {"should", "secure", "easy", "minimal", "etc", "etc."}:
            continue
        examples = "; ".join(f"L{i}" for i, _ in hits[:6])
        add(
            title=f"Vague language: '{term}' ({len(hits)}x)",
            severity=sev,
            category="clarity",
            section=doc.section_for_line(hits[0][0]) or "Document",
            evidence=hits[0][1][:200],
            evidence_verified=True,
            line=hits[0][0],
            issue=f"'{term}' is not testable or is unresolved. Seen at {examples}.",
            failure_scenario="Engineering, QA and stakeholders will each assume a different bar, and disagreements surface after launch.",
            recommendation="Replace with a measurable target (number, unit, percentile) or an owner and a decision date.",
            question_for_pm=f"What exactly does '{term}' mean here, as a number or a decision?",
        )

    # 3. Sensitive data without a privacy section
    sensitive = sorted({t.strip() for t in SENSITIVE_TERMS if t in lower})
    if sensitive and not _find_section(doc, ("privacy", "data protection", "consent")):
        add(
            title="Sensitive data mentioned but no privacy section",
            severity="high",
            category="privacy",
            section="MISSING",
            evidence="",
            evidence_verified=None,
            issue=f"The PRD references potentially sensitive data ({', '.join(sensitive[:8])}) without a privacy section.",
            failure_scenario="Consent, retention and access decisions get made implicitly in code and fail an audit or a breach review.",
            recommendation="Add a data inventory: field, purpose, lawful basis/consent, retention, who can access, where it is processed.",
            question_for_pm="What is the data inventory and retention policy for each sensitive field?",
        )

    # 4. AI with no evaluation / safeguards language
    padded = f" {lower} "
    if any(t in padded for t in AI_TERMS) and not any(t in lower for t in AI_SAFEGUARD_TERMS):
        add(
            title="AI component with no evaluation or fallback plan",
            severity="high",
            category="ai quality",
            section="MISSING",
            evidence="",
            evidence_verified=None,
            issue="The PRD relies on a model but never defines how quality is measured or what happens when it is wrong.",
            failure_scenario="The model ships on vibes, fails on real inputs, and there is no threshold to decide whether to roll back.",
            recommendation="Define an eval set, launch-gating metric thresholds, confidence handling and a human fallback.",
            question_for_pm="What eval result would make you delay launch?",
        )

    # 5. Metrics section with no numbers
    for s in doc.sections:
        if any(k in s.title.lower() for k in ("metric", "kpi", "success")):
            body = "\n".join(s.text.split("\n")[1:])
            if body.strip() and not re.search(r"\d", body):
                add(
                    title="Success metrics have no numbers",
                    severity="high",
                    category="metrics",
                    section=s.title,
                    evidence=next((l.strip() for l in body.split("\n") if l.strip()), "")[:200],
                    evidence_verified=True,
                    line=s.start_line + 1,
                    issue="Metrics are listed without baselines, targets or timeframes.",
                    failure_scenario="After launch every outcome can be spun as success, so bad launches never get rolled back.",
                    recommendation="For each metric: baseline, target, timeframe, and at least one guardrail metric.",
                    question_for_pm="What number, by when, means this launch failed?",
                )
    return findings
